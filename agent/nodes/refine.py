"""refine node: rewrite an offending proposal per the triage verdict (LLM).

Only bad_rule / bad_invariant / bad_relation verdicts are refined; real_bug is a
SUT problem, not a spec problem, and is left to the report. Corrected rules are
appended to ``proposed_rules`` (the reducer accumulates; ``compile_spec`` keeps
the last rule per name, so the correction wins). Invariants and relations are
replaced in place. After ``max_iterations`` the loop stops and the stubborn
proposal is flagged for a human (ADR-0006: 5 iterations).

Each rewrite is majority voted, the same reliability lever triage uses (ADR-0004,
``config.triage_votes``): the proposal is regenerated N times and the plurality of
the discriminating field wins, so a nondeterministic judge that lands the right
correction most of the time is not derailed by a single unlucky draw.
"""

from __future__ import annotations

from collections import Counter

from ..schemas import Invariant, MetamorphicRelation, Rule
from ..state import AgentState

_RULE_SYSTEM = (
    "You are correcting a proposed test rule for a payment intent API that "
    "Hypothesis falsified. Return a corrected Rule with the same name and "
    "operation_id but fixed fields (usually legal_states). Answer only in the "
    "requested structured form."
)
_INV_SYSTEM = (
    "You are correcting or withdrawing a proposed invariant that Hypothesis "
    "falsified against a system assumed correct. Return a corrected Invariant "
    "with the same id and name but a corrected kind if the assumption was wrong. "
    "Answer only in the requested structured form."
)
_REL_SYSTEM = (
    "You are correcting a proposed metamorphic relation that Hypothesis falsified "
    "against a system assumed correct. Keep the same id, name, and transform; fix "
    "fee_handling. Fee model (ADR-0005): a flat fee is charged on every capture and "
    "drawn from external settlement, not the merchant, so it never changes the "
    "merchant balance. A relation is fee_adjusted only when its two runs perform a "
    "different NUMBER of captures, so platform_fees differs by the flat fee times "
    "that difference; when both runs perform the same number of captures it is "
    "exact_equivalence. Scaling amounts keeps the capture count (exact_equivalence); "
    "splitting a capture adds one (fee_adjusted). Use the counterexample to decide. "
    "Answer only in the requested structured form."
)


def _base(proposal_id: str) -> str:
    for suffix in ("_over_limit", "_illegal_state"):
        if proposal_id.endswith(suffix):
            return proposal_id[: -len(suffix)]
    return proposal_id


def _rule_prompt(rule, message: str, counterexample: str) -> str:
    return (
        f"Current proposal: {rule.model_dump()}\n\n"
        f"Falsified by: {message}\n"
        f"Counterexample:\n{counterexample}\n\n"
        "Return the corrected proposal."
    )


def _vote(deps, model, system, prompt, key, votes):
    """Refine a proposal by majority vote, the same reliability lever triage uses
    (ADR-0004). Rewrite N times and keep the ballot whose discriminating field
    (legal_states / kind / fee_handling) is the plurality; a nondeterministic
    judge that lands the right correction most of the time then wins, instead of a
    single unlucky draw deciding the loop. A tie takes the first ballot; the refine
    loop re votes next iteration if it did not converge.
    """
    ballots = [deps.llm.propose(model, system, prompt) for _ in range(votes)]
    if votes == 1:
        return ballots[0]
    winner, _ = Counter(key(b) for b in ballots).most_common(1)[0]
    return next(b for b in ballots if key(b) == winner)


def refine(state: AgentState, deps) -> dict:
    iteration = state.get("iteration", 0) + 1
    verdicts = state.get("triaged_failures", []) or []
    result = state["hypothesis_results"]
    by_ref = {f.tag(): f for f in result.failures}
    rules = {r.name: r for r in state.get("proposed_rules", [])}
    invariants = {i.id: i for i in state.get("proposed_invariants", [])}
    relations = {r.id: r for r in state.get("proposed_relations", []) or []}

    votes = max(1, getattr(deps.config, "triage_votes", 1))
    new_rules: list[Rule] = []
    changed_invariants = dict(invariants)
    changed_relations = dict(relations)
    notes: list[str] = []

    for verdict in verdicts:
        if verdict.classification not in {"bad_rule", "bad_invariant", "bad_relation"}:
            continue
        failure = by_ref.get(verdict.failure_ref)
        if failure is None:
            continue
        if verdict.classification == "bad_rule":
            target = verdict.target or _base(failure.proposal_id)
            current = rules.get(target)
            if current is None:
                continue
            corrected = _vote(
                deps, Rule, _RULE_SYSTEM,
                _rule_prompt(current, failure.message, failure.counterexample),
                lambda r: tuple(sorted(r.legal_states)), votes,
            )
            corrected.name = current.name
            corrected.operation_id = current.operation_id
            new_rules.append(corrected)
            notes.append(f"refine: rewrote rule {corrected.name} -> legal={corrected.legal_states}")
        elif verdict.classification == "bad_invariant":
            target = verdict.target or failure.proposal_id
            current = invariants.get(target)
            if current is None:
                continue
            corrected = _vote(
                deps, Invariant, _INV_SYSTEM,
                _rule_prompt(current, failure.message, failure.counterexample),
                lambda i: i.kind, votes,
            )
            corrected.id = current.id
            corrected.name = current.name
            changed_invariants[current.id] = corrected
            notes.append(f"refine: rewrote invariant {corrected.id} -> {corrected.kind}")
        else:  # bad_relation
            target = verdict.target or failure.proposal_id
            current = relations.get(target)
            if current is None:
                continue
            corrected = _vote(
                deps, MetamorphicRelation, _REL_SYSTEM,
                _rule_prompt(current, failure.message, failure.counterexample),
                lambda r: r.fee_handling, votes,
            )
            corrected.id = current.id
            corrected.name = current.name
            corrected.transform = current.transform
            changed_relations[current.id] = corrected
            notes.append(
                f"refine: rewrote relation {corrected.id} -> fee_handling={corrected.fee_handling}"
            )

    out: dict = {"iteration": iteration, "history": notes or [f"refine: iteration {iteration}, no fixable proposals"]}
    if new_rules:
        out["proposed_rules"] = new_rules  # reducer appends; compile keeps last per name
    if changed_invariants != invariants:
        out["proposed_invariants"] = list(changed_invariants.values())
    if changed_relations != relations:
        out["proposed_relations"] = list(changed_relations.values())
    return out
