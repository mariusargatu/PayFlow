"""No information transforms for the AGENT-MR relations (design section 8.6).

These are the transforms whose whole point is that they carry no signal: the
triage verdict must be invariant under all of them. Ordering and padding are
purely mechanical (no LLM), so they are computed here at test time; paraphrases
are precomputed in ``fixtures.py``. Each builder returns a triage ``AgentState``
ready to hand to the real ``triage`` node.
"""

from __future__ import annotations

from agent.schemas import Failure, TestRunResult
from fixtures import FixtureFailure, TriageFixture

_PAD_BLOCK = (
    "E       accounts_pad = state.create_account()\n"
    "E       state.captured_le_authorized()\n"
    "E       state.conservation_zero()\n"
    "E       state.nonneg_balance()\n"
    "E       state.refunded_le_captured()"
)


def pad_counterexample(counterexample: str) -> str:
    """Insert one harmless, successful step early in the sequence.

    The padding lands right after the machine is constructed and before the step
    that fails at the end, so the failure point is untouched. Only meaningful for
    sequence shaped counterexamples; callers gate on ``sequence_shaped``.
    """
    lines = counterexample.splitlines()
    for index, line in enumerate(lines):
        if "PayFlowGeneratedMachine()" in line:
            return "\n".join(lines[: index + 1] + [_PAD_BLOCK] + lines[index + 1 :])
    # No machine construction anchor: prepend after the header line instead.
    return "\n".join(lines[:1] + [_PAD_BLOCK] + lines[1:])


def _failure(ff: FixtureFailure, *, paraphrase: int | None = None, pad: bool = False) -> Failure:
    message = ff.message if paraphrase is None else ff.paraphrases[paraphrase]
    counterexample = pad_counterexample(ff.counterexample) if pad else ff.counterexample
    return Failure(
        kind=ff.kind,
        proposal_id=ff.proposal_id,
        message=message,
        counterexample=counterexample,
    )


def build_state(
    fixture: TriageFixture,
    failures: list[Failure],
) -> dict:
    """Assemble the triage AgentState from a fixture's proposal context."""
    return {
        "hypothesis_results": TestRunResult(passed=False, failures=failures),
        "proposed_rules": list(fixture.rules),
        "proposed_invariants": list(fixture.invariants),
        "proposed_relations": list(fixture.relations),
        "endpoints": list(fixture.endpoints),
    }


def single_failure_state(
    fixture: TriageFixture,
    ff: FixtureFailure,
    *,
    paraphrase: int | None = None,
    pad: bool = False,
) -> dict:
    return build_state(fixture, [_failure(ff, paraphrase=paraphrase, pad=pad)])


def batch_state(fixtures: list[TriageFixture], *, reverse: bool = False) -> dict:
    """One triage batch spanning several fixtures, with a merged proposal context.

    The failures list is the natural union of every fixture's failures; ``reverse``
    flips its order for AGENT-MR-1. The proposal context is merged across fixtures
    so triage sees the same world in both orderings.
    """
    failures = [_failure(ff) for fx in fixtures for ff in fx.failures]
    if reverse:
        failures = list(reversed(failures))
    rules = _dedupe([r for fx in fixtures for r in fx.rules], key=lambda r: r.name)
    invariants = _dedupe([i for fx in fixtures for i in fx.invariants], key=lambda i: i.id)
    relations = _dedupe([r for fx in fixtures for r in fx.relations], key=lambda r: r.id)
    return {
        "hypothesis_results": TestRunResult(passed=False, failures=failures),
        "proposed_rules": rules,
        "proposed_invariants": invariants,
        "proposed_relations": relations,
    }


def _dedupe(items: list, key) -> list:
    seen: dict = {}
    for item in items:
        seen[key(item)] = item
    return list(seen.values())
