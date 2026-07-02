"""Structural interfaces the domain depends on.

The infrastructure layer provides concrete implementations; the domain stays
decoupled from persistence details. A ``Conn`` is an opaque transaction handle.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol

from .models import Account, Intent, LedgerPair, OperationResult

Conn = Any


class StoredIdempotency(Protocol):
    fingerprint: str
    status: int
    body: dict


class Database(Protocol):
    def transaction(self, immediate: bool = ...) -> AbstractContextManager[Conn]: ...
    def reader(self) -> AbstractContextManager[Conn]: ...


class IdempotencyStore(Protocol):
    def get(self, conn: Conn, key: str) -> StoredIdempotency | None: ...
    def insert(
        self, conn: Conn, key: str, fingerprint: str, result: OperationResult
    ) -> None: ...


class AccountStore(Protocol):
    def get(self, conn: Conn, account_id: str) -> Account | None: ...
    def insert(self, conn: Conn, account: Account) -> None: ...


class IntentStore(Protocol):
    def get(self, conn: Conn, intent_id: str) -> Intent | None: ...
    def insert(self, conn: Conn, intent: Intent) -> None: ...
    def save(self, conn: Conn, intent: Intent) -> None: ...


class LedgerWriter(Protocol):
    def write(self, conn: Conn, pairs: list[LedgerPair]) -> None: ...
    def balance_of(self, conn: Conn, account_id: str) -> int: ...
