"""Idempotency key SQL primitives. Domain free (bodies stored as JSON text)."""

from __future__ import annotations

import sqlite3


def get(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT fingerprint, status, body FROM idempotency_keys WHERE key = ?",
        (key,),
    ).fetchone()


def insert(
    conn: sqlite3.Connection,
    *,
    key: str,
    fingerprint: str,
    status: int,
    body: str,
    created_at: str,
) -> None:
    conn.execute(
        "INSERT INTO idempotency_keys (key, fingerprint, status, body, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (key, fingerprint, status, body, created_at),
    )
