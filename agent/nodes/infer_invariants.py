"""infer_invariants node: propose system wide invariants (LLM, runs after fan in).

Sees the merged rule set and proposes which invariant families hold. The
compiler owns each family's concrete HTTP check; the model's job is to select
the ones that apply and bind them, from a closed vocabulary the compiler can
enact over the API alone.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..golden import GOLDEN_INVARIANTS
from ..schemas import Invariant
from ..state import AgentState


class _InvariantList(BaseModel):
    invariants: list[Invariant]


_SYSTEM = (
    "You are a test engineer choosing which system wide invariants a payment "
    "intent API must satisfy after every request, so a property based test can "
    "assert them. Answer only in the requested structured form."
)

_VOCAB = (
    "Choose from these invariant kinds (each is checkable over the HTTP API):\n"
    "- captured_le_authorized: captured_amount <= authorized_amount always.\n"
    "- refunded_le_captured: refunded_amount <= captured_amount always.\n"
    "- conservation_zero: money is conserved (each merchant's balance equals "
    "its captures minus fees minus refunds).\n"
    "- nonneg_balance: merchant, holds and platform fee balances never go "
    "negative.\n"
    "For each invariant that genuinely holds for this API, give: id (e.g. INV-1), "
    "name (a python identifier), kind (one of the above), description."
)


def _prompt(state: AgentState) -> str:
    rules = state.get("proposed_rules", [])
    lines = [
        f"- {r.name}: {r.kind}/{r.effect}, legal in {r.legal_states or 'n/a'}"
        for r in rules
    ]
    return (
        "The inferred operations of the payment intent API:\n"
        + "\n".join(lines)
        + "\n\n"
        + _VOCAB
    )


def infer_invariants(state: AgentState, deps) -> dict:
    if deps.offline or deps.llm is None:
        return {
            "proposed_invariants": list(GOLDEN_INVARIANTS),
            "history": ["infer_invariants: offline golden invariants"],
        }
    result = deps.llm.propose(_InvariantList, _SYSTEM, _prompt(state))
    invariants = result.invariants
    return {
        "proposed_invariants": invariants,
        "history": [
            "infer_invariants: proposed " + ", ".join(f"{i.id}({i.kind})" for i in invariants)
        ],
    }
