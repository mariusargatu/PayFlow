"""Application service: the eight operations, orchestrated over the ports.

Every POST operation runs through the idempotency strategy; the resulting body
is what gets stored, so a replay is byte identical by construction.
"""

from __future__ import annotations

from . import fees, state_machine as sm
from .errors import NotFoundError, ValidationError
from .idempotency import Operation
from .models import (
    ACCT_EXTERNAL_SETTLEMENT,
    ACCT_HOLDS,
    ACCT_PLATFORM_FEES,
    Account,
    AccountType,
    EntryType,
    Intent,
    LedgerPair,
    OperationResult,
    State,
)
from .ports import AccountStore, Conn, Database, IntentStore, LedgerWriter
from .seams import Clock, IdGenerator


def _account_body(account: Account) -> dict:
    return {
        "id": account.id,
        "name": account.name,
        "type": account.type.value,
        "created_at": account.created_at,
    }


def _intent_body(intent: Intent) -> dict:
    return {
        "id": intent.id,
        "merchant_account_id": intent.merchant_account_id,
        "amount": intent.amount,
        "state": intent.state.value,
        "authorized_amount": intent.authorized_amount,
        "captured_amount": intent.captured_amount,
        "refunded_amount": intent.refunded_amount,
        "created_at": intent.created_at,
    }


def _require_positive(amount: int, label: str) -> None:
    if amount < 1:
        raise ValidationError(f"{label} must be an integer >= 1, got {amount}")


class Idempotency:
    def run(self, key: str, endpoint: str, payload: dict, operation: Operation) -> OperationResult: ...


class PaymentService:
    def __init__(
        self,
        db: Database,
        accounts: AccountStore,
        intents: IntentStore,
        ledger: LedgerWriter,
        idempotency: Idempotency,
        clock: Clock,
        id_generator: IdGenerator,
        capture_fee: int,
    ) -> None:
        self._db = db
        self._accounts = accounts
        self._intents = intents
        self._ledger = ledger
        self._idempotency = idempotency
        self._clock = clock
        self._ids = id_generator
        self._fee = capture_fee

    # -- lookups -----------------------------------------------------------

    def _load_intent(self, conn: Conn, intent_id: str) -> Intent:
        intent = self._intents.get(conn, intent_id)
        if intent is None:
            raise NotFoundError(f"unknown payment intent {intent_id}")
        return intent

    def _load_merchant(self, conn: Conn, account_id: str) -> Account:
        account = self._accounts.get(conn, account_id)
        if account is None or account.type != AccountType.MERCHANT:
            raise NotFoundError(f"unknown merchant account {account_id}")
        return account

    # -- commands ----------------------------------------------------------

    def create_account(self, key: str, name: str) -> OperationResult:
        def op(conn: Conn) -> OperationResult:
            account = Account(
                id=self._ids.account_id(),
                name=name,
                type=AccountType.MERCHANT,
                created_at=self._clock.now().isoformat(),
            )
            self._accounts.insert(conn, account)
            return OperationResult(201, _account_body(account))

        return self._idempotency.run(key, "POST /accounts", {"name": name}, op)

    def create_intent(self, key: str, merchant_account_id: str, amount: int) -> OperationResult:
        _require_positive(amount, "amount")

        def op(conn: Conn) -> OperationResult:
            self._load_merchant(conn, merchant_account_id)
            intent = Intent(
                id=self._ids.intent_id(),
                merchant_account_id=merchant_account_id,
                amount=amount,
                state=State.CREATED,
                authorized_amount=0,
                captured_amount=0,
                refunded_amount=0,
                created_at=self._clock.now().isoformat(),
            )
            self._intents.insert(conn, intent)
            return OperationResult(201, _intent_body(intent))

        payload = {"merchant_account_id": merchant_account_id, "amount": amount}
        return self._idempotency.run(key, "POST /payment_intents", payload, op)

    def authorize(self, key: str, intent_id: str) -> OperationResult:
        def op(conn: Conn) -> OperationResult:
            intent = self._load_intent(conn, intent_id)
            sm.check_authorize(intent)
            authorized = intent.amount
            self._ledger.write(
                conn,
                [LedgerPair(EntryType.AUTHORIZE_HOLD, ACCT_EXTERNAL_SETTLEMENT, ACCT_HOLDS, authorized, intent_id)],
            )
            updated = intent.with_changes(state=State.AUTHORIZED, authorized_amount=authorized)
            self._intents.save(conn, updated)
            return OperationResult(200, _intent_body(updated))

        return self._idempotency.run(key, "POST /payment_intents/authorize", {"id": intent_id}, op)

    def capture(self, key: str, intent_id: str, amount: int | None) -> OperationResult:
        if amount is not None:
            _require_positive(amount, "amount")

        def op(conn: Conn) -> OperationResult:
            intent = self._load_intent(conn, intent_id)
            sm.check_capture(intent)
            remaining = intent.authorized_amount - intent.captured_amount
            captured = amount if amount is not None else remaining
            _require_positive(captured, "capture amount")
            if captured > remaining:
                raise ValidationError(
                    f"capture amount {captured} exceeds remaining hold {remaining}"
                )
            fees.validate_capture_amount(captured, self._fee)
            merchant = intent.merchant_account_id
            pairs = [LedgerPair(EntryType.CAPTURE, ACCT_HOLDS, merchant, captured, intent_id)]
            # The platform fee is drawn from external settlement, not from the
            # merchant (ADR-0005): the merchant keeps the full captured amount, so a
            # full refund returns the merchant to zero and no merchant balance ever
            # goes negative (INV-3). A zero fee (PAYFLOW_CAPTURE_FEE=0 is valid) means
            # no fee pair, since ledger amounts must be strictly positive.
            if self._fee > 0:
                pairs.append(
                    LedgerPair(EntryType.CAPTURE_FEE, ACCT_EXTERNAL_SETTLEMENT, ACCT_PLATFORM_FEES, self._fee, intent_id)
                )
            self._ledger.write(conn, pairs)
            total_captured = intent.captured_amount + captured
            updated = intent.with_changes(
                captured_amount=total_captured,
                state=sm.state_after_capture(intent.authorized_amount, total_captured),
            )
            self._intents.save(conn, updated)
            return OperationResult(200, _intent_body(updated))

        payload = {"id": intent_id, "amount": amount}
        return self._idempotency.run(key, "POST /payment_intents/capture", payload, op)

    def void(self, key: str, intent_id: str) -> OperationResult:
        def op(conn: Conn) -> OperationResult:
            intent = self._load_intent(conn, intent_id)
            sm.check_void(intent)
            pairs: list[LedgerPair] = []
            if intent.state != State.CREATED:
                remaining = intent.authorized_amount - intent.captured_amount
                pairs.append(
                    LedgerPair(EntryType.HOLD_RELEASE, ACCT_HOLDS, ACCT_EXTERNAL_SETTLEMENT, remaining, intent_id)
                )
            self._ledger.write(conn, pairs)
            updated = intent.with_changes(state=State.VOIDED)
            self._intents.save(conn, updated)
            return OperationResult(200, _intent_body(updated))

        return self._idempotency.run(key, "POST /payment_intents/void", {"id": intent_id}, op)

    def refund(self, key: str, intent_id: str, amount: int | None) -> OperationResult:
        if amount is not None:
            _require_positive(amount, "amount")

        def op(conn: Conn) -> OperationResult:
            intent = self._load_intent(conn, intent_id)
            sm.check_refund(intent)
            refundable = intent.captured_amount - intent.refunded_amount
            refund_amount = amount if amount is not None else refundable
            _require_positive(refund_amount, "refund amount")
            if refund_amount > refundable:
                raise ValidationError(
                    f"refund amount {refund_amount} exceeds refundable amount {refundable}"
                )
            self._ledger.write(
                conn,
                [LedgerPair(EntryType.REFUND, intent.merchant_account_id, ACCT_EXTERNAL_SETTLEMENT, refund_amount, intent_id)],
            )
            total_refunded = intent.refunded_amount + refund_amount
            updated = intent.with_changes(
                refunded_amount=total_refunded,
                state=sm.state_after_refund(intent.captured_amount, total_refunded),
            )
            self._intents.save(conn, updated)
            return OperationResult(200, _intent_body(updated))

        payload = {"id": intent_id, "amount": amount}
        return self._idempotency.run(key, "POST /payment_intents/refund", payload, op)

    # -- queries -----------------------------------------------------------

    def get_balance(self, account_id: str) -> dict:
        with self._db.reader() as conn:
            account = self._accounts.get(conn, account_id)
            if account is None:
                raise NotFoundError(f"unknown account {account_id}")
            balance = self._ledger.balance_of(conn, account_id)
        return {"account_id": account_id, "balance": balance}

    def get_intent(self, intent_id: str) -> dict:
        with self._db.reader() as conn:
            intent = self._intents.get(conn, intent_id)
            if intent is None:
                raise NotFoundError(f"unknown payment intent {intent_id}")
        return _intent_body(intent)
