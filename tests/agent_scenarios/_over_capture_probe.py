"""A focused probe that exhibits a broken capture amount check (design section 9).

Scenario (a) hands triage a live build whose over capture guard is dropped. Rather
than lean on the full state machine's random search (which may surface a downstream
cascade failure instead of the over capture itself, making the judged signal
ambiguous), this probe deterministically captures 401 against an authorization of
400 and asserts the correct 422. On the broken build the capture is accepted (200
with captured_amount > authorized_amount), producing the unambiguous
[RULE capture_over_limit] failure that triage should call real_bug.

Not a normal test: the leading underscore keeps it out of default collection; the
execute node runs it by path against the served, rigged SUT.
"""

from __future__ import annotations

import os
import uuid

import httpx

BASE_URL = os.environ.get("PAYFLOW_SUT_BASE_URL", "http://127.0.0.1:8000")


def _key() -> dict:
    return {"Idempotency-Key": uuid.uuid4().hex}


def test_capture_over_limit_rejected():
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        merchant = c.post("/accounts", json={"name": "s1"}, headers=_key()).json()["id"]
        intent = c.post(
            "/payment_intents",
            json={"merchant_account_id": merchant, "amount": 400},
            headers=_key(),
        ).json()["id"]
        c.post(f"/payment_intents/{intent}/authorize", headers=_key())
        response = c.post(
            f"/payment_intents/{intent}/capture", json={"amount": 401}, headers=_key()
        )

    assert response.status_code == 422, (
        f"[RULE capture_over_limit] expected 422 capturing 401 over authorized 400, "
        f"got {response.status_code}: {response.text}"
    )
