"""Determinism seams (specs/constraints.md).

Wall clock time and ID generation live behind injectable providers so property
tests can pin both. These provider classes are the *only* place in the codebase
that call ``datetime.now`` / ``uuid4``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def account_id(self) -> str: ...
    def intent_id(self) -> str: ...
    def ledger_id(self) -> str: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class UuidIdGenerator:
    def account_id(self) -> str:
        return f"acct_{uuid4().hex}"

    def intent_id(self) -> str:
        return f"pi_{uuid4().hex}"

    def ledger_id(self) -> str:
        return f"le_{uuid4().hex}"
