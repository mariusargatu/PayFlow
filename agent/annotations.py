"""Deterministic triage evidence: endpoint context + accepted slice diff.

This is a pre triage disposal step (design section 7.1: the LLM proposes, the
deterministic code disposes). Before triage judges a failure it is handed two
kinds of zero token evidence, computed here without any model call:

  1. the implicated endpoint's OpenAPI summary/description (from ingest), and
  2. an accepted slice comparison: how the failing proposal differs from the
     accepted, committed proposals in ``generated_specs/accepted_proposals.json``.

The output is a mapping from failure_ref to a list of advisory annotation
strings. They are injected into the triage prompt as evidence, never as a
verdict: triage still decides. The whole point of the void rule regression (the
2026-07-02 bigger judge journey entry) is that the accepted slice already knew
void is legal from CREATED, so a falsification of a proposal that omits CREATED
is a bad_rule, not a real_bug; this annotator surfaces exactly that fact.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import EndpointSpec, Failure
from .state import AgentState

DEFAULT_ACCEPTED_PATH = (
    Path(__file__).resolve().parents[1] / "generated_specs" / "accepted_proposals.json"
)

# Negative rule suffixes the compiler appends (agent/codegen/render.py). A failing
# proposal_id like ``void_illegal_state`` maps back to the base rule ``void``.
_RULE_SUFFIXES = ("_over_limit", "_illegal_state")


def _base_rule_name(proposal_id: str) -> str:
    for suffix in _RULE_SUFFIXES:
        if proposal_id.endswith(suffix):
            return proposal_id[: -len(suffix)]
    return proposal_id


def load_accepted(path: str | Path | None = None) -> dict | None:
    """Load the accepted committed slice, or None if it is absent/unreadable."""
    target = Path(path) if path else DEFAULT_ACCEPTED_PATH
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _endpoint_by_operation(state: AgentState, operation_id: str) -> EndpointSpec | None:
    for endpoint in state.get("endpoints", []) or []:
        if endpoint.operation_id == operation_id:
            return endpoint
    return None


def _endpoint_annotation(endpoint: EndpointSpec | None) -> list[str]:
    if endpoint is None:
        return []
    lines = []
    if endpoint.summary:
        lines.append(f"OpenAPI summary for {endpoint.operation_id}: {endpoint.summary}")
    if endpoint.description:
        lines.append(
            f"OpenAPI description for {endpoint.operation_id}: {endpoint.description}"
        )
    return lines


def _states_phrase(states: list[str]) -> str:
    return ", ".join(states) if states else "(none)"


def _rule_annotations(state: AgentState, failure: Failure, accepted: dict) -> list[str]:
    base = _base_rule_name(failure.proposal_id)
    current = next(
        (r for r in state.get("proposed_rules", []) if r.name == base), None
    )
    if current is None:
        return []
    lines = _endpoint_annotation(_endpoint_by_operation(state, current.operation_id))
    accepted_rule = next(
        (r for r in accepted.get("rules", []) if r["operation_id"] == current.operation_id),
        None,
    )
    if accepted_rule is None:
        lines.append(
            f"No rule for operation {current.operation_id} exists in the accepted "
            f"committed slice, so there is no prior decision to compare against."
        )
        return lines
    acc_legal = list(accepted_rule.get("legal_states", []))
    cur_legal = list(current.legal_states or [])
    if acc_legal == cur_legal:
        lines.append(
            f"The accepted committed spec agrees with this proposal: {current.operation_id} "
            f"legal in {_states_phrase(cur_legal)}. A divergence here points at the "
            f"system, not the rule."
        )
        return lines
    missing = [s for s in acc_legal if s not in cur_legal]
    extra = [s for s in cur_legal if s not in acc_legal]
    detail = []
    if missing:
        detail.append(f"this proposal omits {_states_phrase(missing)}")
    if extra:
        detail.append(f"this proposal adds {_states_phrase(extra)}")
    lines.append(
        f"The accepted committed spec lists {current.operation_id} legal from "
        f"{_states_phrase(acc_legal)}; " + "; ".join(detail) + ". A falsification in a "
        f"state the accepted spec treats as legal is evidence the proposed rule is "
        f"wrong (bad_rule), not the system."
    )
    return lines


def _invariant_annotations(state: AgentState, failure: Failure, accepted: dict) -> list[str]:
    current = next(
        (i for i in state.get("proposed_invariants", []) if i.id == failure.proposal_id),
        None,
    )
    if current is None:
        return []
    accepted_inv = next(
        (i for i in accepted.get("invariants", []) if i["id"] == current.id), None
    )
    if accepted_inv is None:
        lines = [
            f"Invariant {current.id} ({current.kind}) is not in the accepted committed "
            f"slice; the accepted invariants are "
            f"{', '.join(i['id'] + ':' + i['kind'] for i in accepted.get('invariants', []))}. "
            f"An assumption absent from the accepted slice that a correct build falsifies "
            f"is evidence of a bad_invariant."
        ]
        return lines
    if accepted_inv["kind"] != current.kind:
        return [
            f"The accepted committed spec binds {current.id} to kind "
            f"{accepted_inv['kind']}, this proposal to {current.kind}."
        ]
    return [
        f"The accepted committed spec agrees {current.id} is {current.kind}; a "
        f"falsification here points at the system."
    ]


def _relation_annotations(state: AgentState, failure: Failure, accepted: dict) -> list[str]:
    current = next(
        (r for r in state.get("proposed_relations", []) or [] if r.id == failure.proposal_id),
        None,
    )
    if current is None:
        return []
    accepted_rel = next(
        (r for r in accepted.get("relations", []) if r["transform"] == current.transform),
        None,
    )
    if accepted_rel is None:
        return [
            f"No relation with transform {current.transform} exists in the accepted "
            f"committed slice, so there is no prior fee_handling decision to compare."
        ]
    if accepted_rel["fee_handling"] != current.fee_handling:
        return [
            f"The accepted committed spec uses fee_handling={accepted_rel['fee_handling']} "
            f"for transform {current.transform}; this proposal uses "
            f"{current.fee_handling}. A mismatch is evidence the relation's fee handling "
            f"is wrong (bad_relation), not the system."
        ]
    return [
        f"The accepted committed spec agrees transform {current.transform} uses "
        f"fee_handling={current.fee_handling}; a falsification here points at the system."
    ]


def annotations_for(state: AgentState, failure: Failure, accepted: dict) -> list[str]:
    if failure.kind == "rule":
        return _rule_annotations(state, failure, accepted)
    if failure.kind == "invariant":
        return _invariant_annotations(state, failure, accepted)
    if failure.kind == "relation":
        return _relation_annotations(state, failure, accepted)
    return []


def build_annotations(
    state: AgentState, path: str | Path | None = None
) -> dict[str, list[str]]:
    """Map each failure_ref to its deterministic advisory annotation lines.

    Returns an empty mapping when the accepted slice is absent: enrichment
    degrades to endpoint context only, never crashes triage.
    """
    accepted = load_accepted(path)
    result: dict[str, list[str]] = {}
    for failure in state["hypothesis_results"].failures:
        if accepted is None:
            # No accepted slice: still offer endpoint context for rule failures.
            base = _base_rule_name(failure.proposal_id)
            current = next(
                (r for r in state.get("proposed_rules", []) if r.name == base), None
            )
            lines = (
                _endpoint_annotation(_endpoint_by_operation(state, current.operation_id))
                if current
                else []
            )
        else:
            lines = annotations_for(state, failure, accepted)
        if lines:
            result[failure.tag()] = lines
    return result
