"""Account SQL primitives. Domain free: the domain layer maps rows to models."""

from __future__ import annotations

import sqlite3


def get(conn: sqlite3.Connection, account_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, name, type, created_at FROM accounts WHERE id = ?",
        (account_id,),
    ).fetchone()


def insert(
    conn: sqlite3.Connection,
    *,
    id: str,
    name: str,
    type: str,
    allow_negative: int,
    created_at: str,
) -> None:
    conn.execute(
        "INSERT INTO accounts (id, name, type, allow_negative, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (id, name, type, allow_negative, created_at),
    )


def insert_if_absent(
    conn: sqlite3.Connection,
    *,
    id: str,
    name: str,
    type: str,
    allow_negative: int,
    created_at: str,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name, type, allow_negative, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (id, name, type, allow_negative, created_at),
    )
