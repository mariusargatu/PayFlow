"""Raw session access for the ledger tables.

Single writer contract (specs/constraints.md): no module other than
``payflow.infrastructure.ledger.core`` may import this module. The Layer 0
``lint-imports`` forbidden contract enforces that structurally.
"""

from __future__ import annotations

import sqlite3


def insert_posting(
    conn: sqlite3.Connection,
    *,
    posting_id: str,
    pair_id: str,
    entry_type: str,
    payment_intent_id: str | None,
    account_id: str,
    direction: str,
    amount: int,
    created_at: str,
) -> None:
    conn.execute(
        "INSERT INTO ledger_postings (id, pair_id, entry_type, payment_intent_id, "
        "account_id, direction, amount, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (posting_id, pair_id, entry_type, payment_intent_id, account_id, direction, amount, created_at),
    )


def balance_of(conn: sqlite3.Connection, account_id: str) -> int:
    row = conn.execute(
        "SELECT "
        "COALESCE(SUM(CASE WHEN direction = 'credit' THEN amount ELSE 0 END), 0) - "
        "COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount ELSE 0 END), 0) AS balance "
        "FROM ledger_postings WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    return int(row["balance"])
