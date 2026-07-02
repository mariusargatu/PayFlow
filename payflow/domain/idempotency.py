"""Idempotency orchestration (specs/api.md).

Two interchangeable strategies selected at startup:

- ``AtomicIdempotency`` (correct): the key check and the side effect share one
  transaction guarded by a write lock, so concurrent same key requests can never
  both execute.
- ``CheckThenActIdempotency`` (``PAYFLOW_BUG=fm_a``): look up the key, run the
  side effect, then insert the key afterwards, no atomicity, a real race.
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable

from .errors import IdempotencyConflictError
from .models import OperationResult
from .ports import Conn, Database, IdempotencyStore

Operation = Callable[[Conn], OperationResult]


def fingerprint(endpoint: str, payload: dict) -> str:
    canonical = json.dumps({"endpoint": endpoint, "payload": payload}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _replay_or_conflict(stored, fp: str) -> OperationResult:
    if stored.fingerprint != fp:
        raise IdempotencyConflictError(
            "idempotency key already used with a different endpoint or payload"
        )
    return OperationResult(status=stored.status, body=stored.body)


class AtomicIdempotency:
    def __init__(self, db: Database, store: IdempotencyStore) -> None:
        self._db = db
        self._store = store

    def run(self, key: str, endpoint: str, payload: dict, operation: Operation) -> OperationResult:
        fp = fingerprint(endpoint, payload)
        with self._db.transaction(immediate=True) as conn:
            stored = self._store.get(conn, key)
            if stored is not None:
                return _replay_or_conflict(stored, fp)
            result = operation(conn)
            self._store.insert(conn, key, fp, result)
            return result


class CheckThenActIdempotency:
    """PAYFLOW_BUG=fm_a: check and act are not atomic (specified broken behavior)."""

    def __init__(self, db: Database, store: IdempotencyStore) -> None:
        self._db = db
        self._store = store

    def run(self, key: str, endpoint: str, payload: dict, operation: Operation) -> OperationResult:
        fp = fingerprint(endpoint, payload)
        with self._db.reader() as conn:
            stored = self._store.get(conn, key)
        if stored is not None:
            return _replay_or_conflict(stored, fp)

        with self._db.transaction(immediate=True) as conn:
            result = operation(conn)

        with self._db.transaction(immediate=True) as conn:
            self._store.insert(conn, key, fp, result)
        return result
