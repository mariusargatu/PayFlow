"""Domain errors carrying the specs/api.md error contract (code + status)."""

from __future__ import annotations


class PayFlowError(Exception):
    """Base error mapped to the JSON error contract."""

    code = "error"
    status = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(PayFlowError):
    code = "not_found"
    status = 404


class InvalidStateError(PayFlowError):
    code = "invalid_state"
    status = 409


class IdempotencyConflictError(PayFlowError):
    code = "idempotency_conflict"
    status = 409


class ValidationError(PayFlowError):
    code = "validation_error"
    status = 422
