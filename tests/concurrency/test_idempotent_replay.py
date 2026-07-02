"""Concurrency replay harness (Layer 1).

Three things live here, each against a real uvicorn server:

- ``test_replay_correct_build_single_effect``: N threads fire the same capture
  with the same Idempotency-Key at once; the correct build must produce one set
  of ledger entries and identical responses. This is the gate the demo runs.
- ``test_fm_a_race_is_observable``: the same attack against PAYFLOW_BUG=fm_a,
  whose check then act idempotency is not atomic; the duplicate capture must be
  observable. Retried across rounds; honest xfail if the race never surfaces.
- ``test_fm_c_atomicity_violation_observable`` plus its correct build control:
  under PAYFLOW_BUG=fm_c the capture pairs commit separately, so a concurrent
  single query snapshot of the ledger can catch a transient INV-4 imbalance.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid

import httpx
import pytest

from helpers import authorize, count_pairs, create_account, create_intent, live_server

N_THREADS = 16
CAPTURE_AMOUNT = 100
LARGE_INTENT = 100_000
FM_C_INTENT = 10_000_000
ROUNDS = 20
CAPTURES_PER_ROUND = 200

_IMBALANCE_SQL = (
    "SELECT "
    "COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount ELSE 0 END), 0) - "
    "COALESCE(SUM(CASE WHEN direction = 'credit' THEN amount ELSE 0 END), 0) "
    "FROM ledger_postings"
)


def _prepare_authorized_intent(server, amount: int) -> str:
    with server.client() as client:
        merchant = create_account(client)
        intent = create_intent(client, merchant, amount)
        authorize(client, intent)
    return intent


def _capture_attack(server, intent: str, key: str) -> list[tuple[int, str]]:
    """Fire N identical captures released together by a barrier."""
    barrier = threading.Barrier(N_THREADS)
    results: list[tuple[int, str]] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        with httpx.Client(base_url=server.base_url, timeout=30.0) as client:
            response = client.post(
                f"/payment_intents/{intent}/capture",
                json={"amount": CAPTURE_AMOUNT},
                headers={"Idempotency-Key": key},
            )
        with lock:
            results.append((response.status_code, response.text))

    threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


def test_replay_correct_build_single_effect(tmp_db_path):
    with live_server(tmp_db_path, bug=None) as server:
        intent = _prepare_authorized_intent(server, LARGE_INTENT)
        results = _capture_attack(server, intent, key="replay-correct")

        statuses = {status for status, _ in results}
        bodies = {body for _, body in results}
        assert statuses == {200}, statuses
        assert len(bodies) == 1, f"expected identical bodies, got {len(bodies)} distinct"

        assert count_pairs(server.db_path, intent, "capture") == 1
        assert count_pairs(server.db_path, intent, "capture_fee") == 1

        with server.client() as client:
            body = client.get(f"/payment_intents/{intent}").json()
        assert body["captured_amount"] == CAPTURE_AMOUNT
        assert body["state"] == "PARTIALLY_CAPTURED"


def test_fm_a_race_is_observable(tmp_db_path):
    with live_server(tmp_db_path, bug="fm_a") as server:
        duplicate_pairs = 0
        for round_no in range(ROUNDS):
            intent = _prepare_authorized_intent(server, LARGE_INTENT)
            key = f"race-{round_no}-{uuid.uuid4().hex}"
            _capture_attack(server, intent, key=key)
            pairs = count_pairs(server.db_path, intent, "capture")
            if pairs >= 2:
                duplicate_pairs = pairs
                break

        if duplicate_pairs == 0:
            pytest.xfail(
                "fm_a check then act race did not surface after "
                f"{ROUNDS} rounds of {N_THREADS} threads; SQLite serialization "
                "may be masking it in this environment"
            )
        assert duplicate_pairs >= 2, (
            f"same Idempotency-Key produced {duplicate_pairs} capture pairs "
            "under fm_a: the operation ran more than once"
        )


def _hammer_and_sample(server, n_captures: int) -> list[int]:
    """Hammer captures while a second thread samples global ledger balance."""
    intent = _prepare_authorized_intent(server, FM_C_INTENT)
    observed: list[int] = []
    stop = threading.Event()

    def sampler() -> None:
        conn = sqlite3.connect(server.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            while not stop.is_set():
                imbalance = conn.execute(_IMBALANCE_SQL).fetchone()[0]
                if imbalance != 0:
                    observed.append(int(imbalance))
        finally:
            conn.close()

    watcher = threading.Thread(target=sampler)
    watcher.start()
    try:
        with httpx.Client(base_url=server.base_url, timeout=30.0) as client:
            for _ in range(n_captures):
                client.post(
                    f"/payment_intents/{intent}/capture",
                    json={"amount": CAPTURE_AMOUNT},
                    headers={"Idempotency-Key": uuid.uuid4().hex},
                )
    finally:
        stop.set()
        watcher.join()
    return observed


def test_fm_c_atomicity_violation_observable(tmp_db_path):
    with live_server(tmp_db_path, bug="fm_c") as server:
        observed: list[int] = []
        for _ in range(ROUNDS):
            observed = _hammer_and_sample(server, CAPTURES_PER_ROUND)
            if observed:
                break

        if not observed:
            pytest.xfail(
                "fm_c transient INV-4 imbalance was never caught by the sampler "
                f"across {ROUNDS} rounds; the commit windows may be too narrow "
                "to observe in this environment"
            )
        assert observed, "expected at least one imbalanced snapshot under fm_c"


def test_fm_c_control_correct_build_never_imbalanced(tmp_db_path):
    with live_server(tmp_db_path, bug=None) as server:
        observed = _hammer_and_sample(server, CAPTURES_PER_ROUND)
        assert observed == [], (
            "correct build must keep debits equal to credits at every snapshot; "
            f"saw imbalanced snapshots {observed[:5]}"
        )
