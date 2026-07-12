"""SQLite database: connection management, schema, and transactions.

Connections are short lived and per operation, which keeps the store thread safe
under the concurrency harness. ``BEGIN IMMEDIATE`` acquires the write lock up
front, serialising concurrent writers; WAL + a busy timeout absorb contention.

Load bearing invariants are pushed into CHECK constraints: amounts stay positive
(INV-3 support), captured <= authorized (INV-1), refunded <= captured (INV-2).
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payment_intents (
    id TEXT PRIMARY KEY,
    merchant_account_id TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount >= 1),
    state TEXT NOT NULL,
    authorized_amount INTEGER NOT NULL DEFAULT 0 CHECK (authorized_amount >= 0),
    captured_amount INTEGER NOT NULL DEFAULT 0 CHECK (captured_amount >= 0),
    refunded_amount INTEGER NOT NULL DEFAULT 0 CHECK (refunded_amount >= 0),
    created_at TEXT NOT NULL,
    CHECK (captured_amount <= authorized_amount),
    CHECK (refunded_amount <= captured_amount)
);

CREATE TABLE IF NOT EXISTS ledger_postings (
    id TEXT PRIMARY KEY,
    pair_id TEXT NOT NULL,
    entry_type TEXT NOT NULL,
    payment_intent_id TEXT,
    account_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
    amount INTEGER NOT NULL CHECK (amount > 0),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_postings_account ON ledger_postings (account_id);
CREATE INDEX IF NOT EXISTS idx_postings_intent ON ledger_postings (payment_intent_id);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    status INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def transaction(self, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
        finally:
            conn.close()

    @contextmanager
    def reader(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()
