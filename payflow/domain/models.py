"""Immutable domain models and stable constants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

# Stable, well known system account IDs (specs/domain.md).
ACCT_EXTERNAL_SETTLEMENT = "acct_external_settlement"
ACCT_PLATFORM_FEES = "acct_platform_fees"
ACCT_HOLDS = "acct_holds"


class AccountType(StrEnum):
    MERCHANT = "merchant"
    EXTERNAL_SETTLEMENT = "external_settlement"
    PLATFORM_FEES = "platform_fees"
    HOLDS = "holds"


class State(StrEnum):
    CREATED = "CREATED"
    AUTHORIZED = "AUTHORIZED"
    PARTIALLY_CAPTURED = "PARTIALLY_CAPTURED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class EntryType(StrEnum):
    AUTHORIZE_HOLD = "authorize_hold"
    CAPTURE = "capture"
    CAPTURE_FEE = "capture_fee"
    HOLD_RELEASE = "hold_release"
    REFUND = "refund"


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    type: AccountType
    created_at: str


@dataclass(frozen=True)
class Intent:
    id: str
    merchant_account_id: str
    amount: int
    state: State
    authorized_amount: int
    captured_amount: int
    refunded_amount: int
    created_at: str

    def with_changes(self, **changes: object) -> "Intent":
        return replace(self, **changes)


@dataclass(frozen=True)
class LedgerPair:
    """One balanced double entry movement (specs/domain.md)."""

    entry_type: EntryType
    debit_account: str
    credit_account: str
    amount: int
    payment_intent_id: str | None


@dataclass(frozen=True)
class OperationResult:
    status: int
    body: dict


@dataclass(frozen=True)
class StoredIdempotency:
    fingerprint: str
    status: int
    body: dict
