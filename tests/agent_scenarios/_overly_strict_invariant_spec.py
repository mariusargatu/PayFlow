"""A deliberately overly strict invariant that a CORRECT PayFlow falsifies.

Used by scenario (b): it asserts captured_amount == authorized_amount after a
legal partial capture, which the correct build violates on purpose (partial
capture is legal). Run against a live SUT by the execute node, it produces an
[INV-9] tagged failure that triage must classify as bad_invariant, not real_bug,
the assumption is wrong, the system is right.

Not a normal test: the leading underscore keeps it out of default collection; the
execute node runs it explicitly by path against the served SUT, exactly as it runs
the committed generated specs.
"""

from __future__ import annotations

import os
import uuid

import httpx

BASE_URL = os.environ.get("PAYFLOW_SUT_BASE_URL", "http://127.0.0.1:8000")


def _key() -> dict:
    return {"Idempotency-Key": uuid.uuid4().hex}


def test_captured_equals_authorized():
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        merchant = c.post("/accounts", json={"name": "s2"}, headers=_key()).json()["id"]
        intent = c.post(
            "/payment_intents",
            json={"merchant_account_id": merchant, "amount": 400},
            headers=_key(),
        ).json()["id"]
        c.post(f"/payment_intents/{intent}/authorize", headers=_key())
        c.post(f"/payment_intents/{intent}/capture", json={"amount": 150}, headers=_key())
        body = c.get(f"/payment_intents/{intent}").json()

    assert body["captured_amount"] == body["authorized_amount"], (
        f"[INV-9] captured_amount {body['captured_amount']} must equal authorized_amount "
        f"{body['authorized_amount']} for a captured intent, but a partial capture left "
        f"them unequal: {body}"
    )
