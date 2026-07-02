"""The single writer to the ledger.

Every ledger row in the system is written here and nowhere else, so ledger
atomicity is a property of one reviewable module. Callers pass fully formed
postings (already expanded from balanced pairs); this module only decides how
they are committed. Domain free by design: the API/domain layers hold the
business meaning, this holds the write.

Two writers, selected at startup:

- ``CorrectLedgerWriter``: every posting lands in the caller's one transaction
  (all or nothing, specs/domain.md).
- ``SplitCommitLedgerWriter`` (``PAYFLOW_BUG=fm_c``): commits each posting
  separately, so a failure between debit and credit violates INV-4.
"""

from __future__ import annotations

import sqlite3
from typing import Mapping, Sequence

from . import tables

Posting = Mapping[str, object]


class CorrectLedgerWriter:
    def write(self, conn: sqlite3.Connection, postings: Sequence[Posting]) -> None:
        for posting in postings:
            tables.insert_posting(conn, **posting)

    def balance_of(self, conn: sqlite3.Connection, account_id: str) -> int:
        return tables.balance_of(conn, account_id)


class SplitCommitLedgerWriter:
    """PAYFLOW_BUG=fm_c: postings committed one at a time (specified broken)."""

    def write(self, conn: sqlite3.Connection, postings: Sequence[Posting]) -> None:
        for posting in postings:
            tables.insert_posting(conn, **posting)
            conn.execute("COMMIT")
            conn.execute("BEGIN IMMEDIATE")

    def balance_of(self, conn: sqlite3.Connection, account_id: str) -> int:
        return tables.balance_of(conn, account_id)
