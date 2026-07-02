"""Human labels for the three property kinds, shared by the run view and the
trust report so the wording never diverges between them.

The category names (rules / invariants / metamorphic relations) are jargon. Each
is really one kind of question you would ask about any payment system:
  - rules:      is this action allowed right now?
  - invariants: is the money still safe, always?
  - relations:  do two equivalent routes agree?

Each entry is (human name, one line gloss, concrete example).
"""

from __future__ import annotations

PROPERTY_LABELS: dict[str, tuple[str, str, str]] = {
    "rules": (
        "lifecycle rules",
        "when each payment action is allowed",
        "e.g. cannot capture before authorize",
    ),
    "invariants": (
        "money safeguards",
        "what must always stay true about the balances",
        "e.g. never capture more than was authorized",
    ),
    "relations": (
        "equivalence checks",
        "different routes must reach the same result",
        "e.g. charging 100 once vs 50 + 50 must match",
    ),
}


# Plain English for every member of the closed vocabularies (agent/schemas.py), so
# any proposed check decomposes to a layperson sentence with no domain knowledge.
_EFFECT_PLAIN = {
    "authorize": "Put a hold on the customer's money (reserve it).",
    "capture": "Take the reserved money, only allowed after it has been held.",
    "refund": "Give money back to the customer, only after it was taken.",
    "void": "Cancel and release the hold, only before the money is taken.",
    "none": "A read or setup step that moves no money (create an account, look up a payment).",
}
_INVARIANT_PLAIN = {
    "captured_le_authorized": "You can never take more money than was approved.",
    "refunded_le_captured": "You can never give back more than was taken.",
    "conservation_zero": "Money is never created or lost; every movement balances to zero.",
    "nonneg_balance": "No account is ever left with a negative balance.",
}
_TRANSFORM_PLAIN = {
    "split_capture": "Taking 100 at once must end the same as taking 50 then 50.",
    "reorder_independent": "Two unrelated payments, run in either order, reach the same result.",
    "scale_amounts": "Multiply every amount by the same number and the balances scale the same way.",
    "replay_request": "Sending the exact same request twice must not charge the customer twice.",
    "void_recreate": "Cancelling then redoing a payment must match doing it once.",
    "split_refund": "Refunding in two parts must end the same as one full refund.",
}


def _get(item, *keys):
    for k in keys:
        v = item.get(k) if isinstance(item, dict) else getattr(item, k, None)
        if v:
            return v
    return ""


def describe(category: str, item) -> str:
    """A plain English sentence for one proposed check, keyed off its closed
    vocabulary field (effect / kind / transform). Empty if it cannot be mapped."""
    if category == "rules":
        return _EFFECT_PLAIN.get(_get(item, "effect"), "")
    if category == "invariants":
        return _INVARIANT_PLAIN.get(_get(item, "kind"), "")
    if category == "relations":
        return _TRANSFORM_PLAIN.get(_get(item, "transform"), "")
    return ""


def human(kind: str) -> str:
    """The human name for a property kind (rules/invariants/relations)."""
    return PROPERTY_LABELS.get(kind, (kind, "", ""))[0]


def counts_phrase(rules: int, invariants: int, relations: int) -> str:
    """A plain reading of an r/i/m triple, e.g.
    '8 lifecycle rules, 4 money safeguards, 6 equivalence checks'."""
    parts = [
        (rules, "rules"),
        (invariants, "invariants"),
        (relations, "relations"),
    ]
    return ", ".join(f"{n} {human(k)}" for n, k in parts if n)
