"""Payment intent SQL primitives. Domain free."""

from __future__ import annotations

import sqlite3


def get(conn: sqlite3.Connection, intent_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, merchant_account_id, amount, state, authorized_amount, "
        "captured_amount, refunded_amount, created_at "
        "FROM payment_intents WHERE id = ?",
        (intent_id,),
    ).fetchone()


def insert(
    conn: sqlite3.Connection,
    *,
    id: str,
    merchant_account_id: str,
    amount: int,
    state: str,
    authorized_amount: int,
    captured_amount: int,
    refunded_amount: int,
    created_at: str,
) -> None:
    conn.execute(
        "INSERT INTO payment_intents (id, merchant_account_id, amount, state, "
        "authorized_amount, captured_amount, refunded_amount, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            id,
            merchant_account_id,
            amount,
            state,
            authorized_amount,
            captured_amount,
            refunded_amount,
            created_at,
        ),
    )


def update(
    conn: sqlite3.Connection,
    *,
    id: str,
    state: str,
    authorized_amount: int,
    captured_amount: int,
    refunded_amount: int,
) -> None:
    conn.execute(
        "UPDATE payment_intents SET state = ?, authorized_amount = ?, "
        "captured_amount = ?, refunded_amount = ? WHERE id = ?",
        (state, authorized_amount, captured_amount, refunded_amount, id),
    )
