"""Shared plumbing for the Phase 1 test layers.

Two capabilities live here: starting a real PayFlow server in a subprocess
(uvicorn on a free port, its own temp SQLite file, optional PAYFLOW_BUG), and
reading that same SQLite file directly for assertions. Tests may bypass the API
to *observe* the ledger; they never bypass it to *mutate*.
"""

from __future__ import annotations

import contextlib
import socket
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass

import httpx


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class LiveServer:
    process: subprocess.Popen
    base_url: str
    db_path: str

    def client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=30.0)


def _server_env(db_path: str, bug: str | None, capture_fee: int | None) -> dict:
    import os

    env = dict(os.environ)
    env["PAYFLOW_DB_PATH"] = db_path
    env.pop("PAYFLOW_BUG", None)
    if bug is not None:
        env["PAYFLOW_BUG"] = bug
    if capture_fee is not None:
        env["PAYFLOW_CAPTURE_FEE"] = str(capture_fee)
    return env


@contextlib.contextmanager
def live_server(db_path: str, bug: str | None = None, capture_fee: int | None = None):
    """Start uvicorn in a subprocess and tear it down on exit."""
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "payflow.api.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    process = subprocess.Popen(cmd, env=_server_env(db_path, bug, capture_fee))
    try:
        _await_ready(base_url, process)
        yield LiveServer(process=process, base_url=base_url, db_path=db_path)
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def _await_ready(base_url: str, process: subprocess.Popen, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited early with code {process.returncode}")
        try:
            response = httpx.get(f"{base_url}/openapi.json", timeout=1.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.05)
    raise RuntimeError("server did not become ready in time")


# -- API convenience calls -------------------------------------------------


def create_account(client: httpx.Client, name: str = "acme", key: str | None = None) -> str:
    key = key or _fresh_key()
    response = client.post("/accounts", json={"name": name}, headers={"Idempotency-Key": key})
    response.raise_for_status()
    return response.json()["id"]


def create_intent(client: httpx.Client, merchant_id: str, amount: int, key: str | None = None) -> str:
    key = key or _fresh_key()
    response = client.post(
        "/payment_intents",
        json={"merchant_account_id": merchant_id, "amount": amount},
        headers={"Idempotency-Key": key},
    )
    response.raise_for_status()
    return response.json()["id"]


def authorize(client: httpx.Client, intent_id: str, key: str | None = None) -> None:
    key = key or _fresh_key()
    response = client.post(
        f"/payment_intents/{intent_id}/authorize", headers={"Idempotency-Key": key}
    )
    response.raise_for_status()


def _fresh_key() -> str:
    import uuid

    return uuid.uuid4().hex


# -- direct SQLite observation (assertions only, never mutation) ------------


def _read_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def global_imbalance(db_path: str) -> int:
    """Single query INV-4 probe: total debits minus total credits."""
    with contextlib.closing(_read_connection(db_path)) as conn:
        row = conn.execute(
            "SELECT "
            "COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount ELSE 0 END), 0) - "
            "COALESCE(SUM(CASE WHEN direction = 'credit' THEN amount ELSE 0 END), 0) "
            "AS imbalance FROM ledger_postings"
        ).fetchone()
        return int(row["imbalance"])


def count_pairs(db_path: str, intent_id: str, entry_type: str) -> int:
    """How many balanced pairs of one entry type exist for an intent.

    Counts debit postings, since every committed pair contributes exactly one
    debit and one credit.
    """
    with contextlib.closing(_read_connection(db_path)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM ledger_postings "
            "WHERE payment_intent_id = ? AND entry_type = ? AND direction = 'debit'",
            (intent_id, entry_type),
        ).fetchone()
        return int(row["n"])
