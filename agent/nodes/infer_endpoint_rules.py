"""infer_endpoint_rules node: propose a rule for one endpoint (LLM, Send fan out).

This node runs once per endpoint via LangGraph's ``Send`` (design section 7.5):
the dispatcher in ``graph.py`` emits one task per operation, each carrying its
endpoint in ``current_endpoint``. The node asks the model to bind that single
operation to a payment effect, its legal precondition states, and its amount
field. Results append into ``proposed_rules`` through the state reducer.
"""

from __future__ import annotations

from ..schemas import Rule
from ..state import AgentState

_STATES = "CREATED, AUTHORIZED, PARTIALLY_CAPTURED, CAPTURED, PARTIALLY_REFUNDED, REFUNDED, VOIDED"

_SYSTEM = (
    "You are a test engineer inferring the behavioural contract of a payment "
    "intent API from its OpenAPI operations, so a property based test can drive "
    "it. A payment intent moves through these states: "
    f"{_STATES}. You reason about one operation at a time and answer only in the "
    "requested structured form."
)



def _prompt(endpoint) -> str:
    return (
        f"Operation: {endpoint.operation_id}\n"
        f"HTTP: {endpoint.http_method} {endpoint.path}\n"
        f"Summary: {endpoint.summary}\n"
        f"Request body fields: {endpoint.body_fields or 'none'}\n\n"
        "Classify this operation for a stateful test model:\n"
        "- kind: create_account (makes a merchant account), create_intent (makes "
        "a new payment intent in CREATED), intent_transition (acts on an existing "
        "intent and may change its state), or query (a read that changes nothing).\n"
        "- effect: for intent_transition, which payment effect it has "
        "(authorize, capture, refund, void); otherwise none.\n"
        "- legal_states: for intent_transition, the exact intent states in which "
        "the call SUCCEEDS. Consider partial capture and partial refund flows. "
        "Empty for other kinds.\n"
        "- amount_field: the request body field carrying an integer amount, or null.\n"
        "- success_status: the HTTP status of a successful call.\n"
        "- name: a short python identifier for the generated rule (e.g. 'capture').\n"
    )


def infer_endpoint_rules(state: AgentState, deps) -> dict:
    endpoint = state["current_endpoint"]
    rule = deps.llm.propose(Rule, _SYSTEM, _prompt(endpoint))
    rule.operation_id = endpoint.operation_id
    return {
        "proposed_rules": [rule],
        "history": [
            f"infer_endpoint_rules[{endpoint.operation_id}]: {rule.kind}/{rule.effect} "
            f"legal={rule.legal_states}"
        ],
    }
