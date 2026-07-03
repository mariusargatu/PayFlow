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
    # Sum in Python (arbitrary precision) rather than with SQLite's SUM, whose int64
    # accumulator raises OperationalError('integer overflow') once an aggregate
    # exceeds 2**63-1 even though every individual amount is within the schema bound.
    # That would surface as a 500 on a query the API accepts; a Python sum keeps the
    # balance an exact integer and never overflows.
    rows = conn.execute(
        "SELECT direction, amount FROM ledger_postings WHERE account_id = ?",
        (account_id,),
    ).fetchall()
    return sum(r["amount"] if r["direction"] == "credit" else -r["amount"] for r in rows)
