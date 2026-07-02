"""Flat platform fee on every successful capture (specs/domain.md)."""

from __future__ import annotations

from .errors import ValidationError


def validate_capture_amount(amount: int, fee: int) -> None:
    """A capture must be economically larger than the fee it generates, so amount > fee.

    The fee is drawn from external settlement, not the merchant (ADR-0005), so this
    is a platform business rule (no capture smaller than its own fee), not a
    solvency requirement.
    """
    if amount <= fee:
        raise ValidationError(
            f"capture amount {amount} must be greater than the capture fee {fee}"
        )
