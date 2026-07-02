"""Payment intent state machine (specs/state-machine.md).

Pure functions: given a current intent and an operation, decide the resulting
state or raise. No operation ever picks its target state freely.
"""

from __future__ import annotations

from .errors import InvalidStateError
from .models import Intent, State

_AUTHORIZE_FROM = frozenset({State.CREATED})
_CAPTURE_FROM = frozenset({State.AUTHORIZED, State.PARTIALLY_CAPTURED})
_VOID_FROM = frozenset({State.CREATED, State.AUTHORIZED, State.PARTIALLY_CAPTURED})
_REFUND_FROM = frozenset({State.CAPTURED, State.PARTIALLY_REFUNDED})


def _require(current: State, allowed: frozenset[State], operation: str) -> None:
    if current not in allowed:
        raise InvalidStateError(
            f"cannot {operation} an intent in state {current.value}; "
            f"allowed states are {sorted(s.value for s in allowed)}"
        )


def check_authorize(intent: Intent) -> None:
    _require(intent.state, _AUTHORIZE_FROM, "authorize")


def check_capture(intent: Intent) -> None:
    _require(intent.state, _CAPTURE_FROM, "capture")


def check_void(intent: Intent) -> None:
    _require(intent.state, _VOID_FROM, "void")


def check_refund(intent: Intent) -> None:
    _require(intent.state, _REFUND_FROM, "refund")


def state_after_capture(authorized_amount: int, captured_amount: int) -> State:
    return State.CAPTURED if captured_amount == authorized_amount else State.PARTIALLY_CAPTURED


def state_after_refund(captured_amount: int, refunded_amount: int) -> State:
    return State.REFUNDED if refunded_amount == captured_amount else State.PARTIALLY_REFUNDED
