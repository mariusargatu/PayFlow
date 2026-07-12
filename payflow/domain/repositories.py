"""Domain side repository adapters.

These implement the domain ports by mapping between domain models and the
infrastructure SQL primitives. This is the ``domain -> infrastructure`` edge:
the domain owns the models and the mapping; infrastructure stays domain free.
"""

from __future__ import annotations

import json
import sqlite3

from ..infrastructure import accounts as accounts_sql
from ..infrastructure import idempotency as idempotency_sql
from ..infrastructure import intents as intents_sql
from ..infrastructure.ledger.core import CorrectLedgerWriter, SplitCommitLedgerWriter
from .models import (
    Account,
    AccountType,
    Intent,
    LedgerPair,
    OperationResult,
    State,
    StoredIdempotency,
)
from .seams import Clock, IdGenerator

_LedgerBackend = CorrectLedgerWriter | SplitCommitLedgerWriter


class AccountsRepository:
    def get(self, conn: sqlite3.Connection, account_id: str) -> Account | None:
        row = accounts_sql.get(conn, account_id)
        if row is None:
            return None
        return Account(
            id=row["id"],
            name=row["name"],
            type=AccountType(row["type"]),
            created_at=row["created_at"],
        )

    def insert(self, conn: sqlite3.Connection, account: Account) -> None:
        accounts_sql.insert(
            conn,
            id=account.id,
            name=account.name,
            type=account.type.value,
            created_at=account.created_at,
        )

    def insert_if_absent(self, conn: sqlite3.Connection, account: Account) -> None:
        accounts_sql.insert_if_absent(
            conn,
            id=account.id,
            name=account.name,
            type=account.type.value,
            created_at=account.created_at,
        )


class IntentsRepository:
    def get(self, conn: sqlite3.Connection, intent_id: str) -> Intent | None:
        row = intents_sql.get(conn, intent_id)
        if row is None:
            return None
        return Intent(
            id=row["id"],
            merchant_account_id=row["merchant_account_id"],
            amount=row["amount"],
            state=State(row["state"]),
            authorized_amount=row["authorized_amount"],
            captured_amount=row["captured_amount"],
            refunded_amount=row["refunded_amount"],
            created_at=row["created_at"],
        )

    def insert(self, conn: sqlite3.Connection, intent: Intent) -> None:
        intents_sql.insert(
            conn,
            id=intent.id,
            merchant_account_id=intent.merchant_account_id,
            amount=intent.amount,
            state=intent.state.value,
            authorized_amount=intent.authorized_amount,
            captured_amount=intent.captured_amount,
            refunded_amount=intent.refunded_amount,
            created_at=intent.created_at,
        )

    def save(self, conn: sqlite3.Connection, intent: Intent) -> None:
        intents_sql.update(
            conn,
            id=intent.id,
            state=intent.state.value,
            authorized_amount=intent.authorized_amount,
            captured_amount=intent.captured_amount,
            refunded_amount=intent.refunded_amount,
        )


class IdempotencyRepository:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def get(self, conn: sqlite3.Connection, key: str) -> StoredIdempotency | None:
        row = idempotency_sql.get(conn, key)
        if row is None:
            return None
        return StoredIdempotency(
            fingerprint=row["fingerprint"],
            status=row["status"],
            body=json.loads(row["body"]),
        )

    def insert(
        self, conn: sqlite3.Connection, key: str, fingerprint: str, result: OperationResult
    ) -> None:
        idempotency_sql.insert(
            conn,
            key=key,
            fingerprint=fingerprint,
            status=result.status,
            body=json.dumps(result.body),
            created_at=self._clock.now().isoformat(),
        )


class LedgerRepository:
    """Expands balanced pairs into append only postings, then delegates the write."""

    def __init__(self, backend: _LedgerBackend, clock: Clock, id_generator: IdGenerator) -> None:
        self._backend = backend
        self._clock = clock
        self._ids = id_generator

    def write(self, conn: sqlite3.Connection, pairs: list[LedgerPair]) -> None:
        now = self._clock.now().isoformat()
        postings: list[dict] = []
        for pair in pairs:
            pair_id = self._ids.ledger_id()
            base = {
                "pair_id": pair_id,
                "entry_type": pair.entry_type.value,
                "payment_intent_id": pair.payment_intent_id,
                "amount": pair.amount,
                "created_at": now,
            }
            postings.append(
                {"posting_id": f"{pair_id}_d", "account_id": pair.debit_account, "direction": "debit", **base}
            )
            postings.append(
                {"posting_id": f"{pair_id}_c", "account_id": pair.credit_account, "direction": "credit", **base}
            )
        self._backend.write(conn, postings)

    def balance_of(self, conn: sqlite3.Connection, account_id: str) -> int:
        return self._backend.balance_of(conn, account_id)
