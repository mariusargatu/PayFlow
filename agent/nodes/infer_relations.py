"""infer_relations node: propose metamorphic relations (LLM, design section 8).

A metamorphic relation pairs a scenario TRANSFORM with an EXPECTED RELATION
between two runs (design section 5.6). The model selects transforms from a closed
vocabulary the compiler can enact and, for each, reasons about the flat per
capture fee (spec section 3): a transform that changes the number of captures
changes the total fee, so its relation needs the exact fee deviation term rather
than plain equivalence.

Design principle (section 7.1): the model only proposes the binding (which
transform, exact_equivalence vs fee_adjusted). It never sees the exact deviation
arithmetic or the answer key; the compiler owns the arithmetic, and a wrong fee
choice is falsified by Hypothesis and repaired by refine. The prompt deliberately
does not tell the model which transforms need the fee term.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..schemas import MetamorphicRelation
from ..state import AgentState


class _RelationList(BaseModel):
    relations: list[MetamorphicRelation]


_SYSTEM = (
    "You are a test engineer proposing metamorphic relations for a payment intent "
    "API. A metamorphic relation runs a scenario twice under a transform that "
    "should relate the two runs' final balances and intent states in a known way, "
    "which catches inconsistencies no single run invariant can. Answer only in the "
    "requested structured form."
)

_VOCAB = (
    "Propose relations using only these transforms (each is one the test compiler "
    "can execute against the live API):\n"
    "- split_capture: replace one capture of N with two sequential captures "
    "N1+N2=N on the same intent.\n"
    "- reorder_independent: swap the execution order of operations on two disjoint "
    "merchant accounts.\n"
    "- scale_amounts: multiply every monetary amount in the scenario by an integer "
    "k.\n"
    "- replay_request: resubmit an identical request (same idempotency key, same "
    "payload) one or more times.\n"
    "- void_recreate: void an intent and immediately create an identical "
    "replacement, then proceed.\n"
    "- split_refund: capture an amount in full, then refund it either as one "
    "refund of N or as two sequential partial refunds N1+N2=N on the same "
    "intent.\n\n"
    "This API charges a FLAT platform fee on EVERY successful capture (partial "
    "captures each incur it). For each transform that yields a sound relation, "
    "give: id (e.g. MR-1), name (a python identifier), transform (one of the "
    "above), fee_handling, description, rationale. For fee_handling choose "
    "exact_equivalence if the two runs' final balances must be identical, or "
    "fee_adjusted if the transform changes how many captures happen and therefore "
    "the total fee, so the balances differ by an exact fee deviation term. Reason "
    "it through per transform; do not assume."
)


def _prompt(state: AgentState) -> str:
    rules = state.get("proposed_rules", [])
    effects = sorted({r.effect for r in rules if r.effect != "none"})
    ops = ", ".join(effects) or "authorize, capture, refund, void"
    return (
        f"The API supports these payment effects: {ops}. Amounts are integer minor "
        "units; a flat platform fee is charged on every capture.\n\n" + _VOCAB
    )


def infer_relations(state: AgentState, deps) -> dict:
    result = deps.llm.propose(_RelationList, _SYSTEM, _prompt(state))
    relations = result.relations
    return {
        "proposed_relations": relations,
        "history": [
            "infer_relations: proposed "
            + ", ".join(f"{r.id}({r.transform}/{r.fee_handling})" for r in relations)
        ],
    }
