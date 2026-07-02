"""Hand written Hypothesis sanity machine (Layer 1 plumbing check).

This is deliberately modest: it proves the stateful harness can drive PayFlow
through legal sequences and that a few load bearing invariants hold. The real
property discovery is the Phase 2 agent's job, not this file.

The machine drives the API through ``fastapi.testclient.TestClient`` against a
fresh temp SQLite file per machine instance. It tracks the state it expects and
compares that to what the API reports (INV-5), checks captured never exceeds
authorized (INV-1), and reads the SQLite file directly for the global debit
equals credit balance (INV-4). It also fires illegal operations and asserts a
409 with no change.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from hypothesis import settings
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule
from hypothesis.strategies import integers

from payflow.api.app import create_app
from payflow.config import Config
from helpers import global_imbalance

CAPTURE_FEE = 30

_LEGAL_CAPTURE = {"AUTHORIZED", "PARTIALLY_CAPTURED"}
_LEGAL_VOID = {"CREATED", "AUTHORIZED", "PARTIALLY_CAPTURED"}
_LEGAL_REFUND = {"CAPTURED", "PARTIALLY_REFUNDED"}


def _key() -> dict:
    return {"Idempotency-Key": uuid.uuid4().hex}


class PayFlowMachine(RuleBasedStateMachine):
    accounts = Bundle("accounts")
    intents = Bundle("intents")

    def __init__(self) -> None:
        super().__init__()
        self._dir = tempfile.mkdtemp(prefix="payflow_prop_")
        db_path = str(Path(self._dir) / "payflow.db")
        self._db_path = db_path
        config = Config(db_path=db_path, capture_fee=CAPTURE_FEE, bug=None)
        self._client = TestClient(create_app(config))
        self._model: dict[str, dict] = {}

    def teardown(self) -> None:
        self._client.close()
        shutil.rmtree(self._dir, ignore_errors=True)

    # -- rules: legal operations ------------------------------------------

    @rule(target=accounts)
    def create_account(self):
        response = self._client.post("/accounts", json={"name": "acme"}, headers=_key())
        assert response.status_code == 201, response.text
        return response.json()["id"]

    @rule(target=intents, account=accounts, amount=integers(min_value=100, max_value=100_000))
    def create_intent(self, account, amount):
        response = self._client.post(
            "/payment_intents",
            json={"merchant_account_id": account, "amount": amount},
            headers=_key(),
        )
        assert response.status_code == 201, response.text
        intent_id = response.json()["id"]
        self._model[intent_id] = {
            "amount": amount,
            "authorized": 0,
            "captured": 0,
            "refunded": 0,
            "state": "CREATED",
        }
        return intent_id

    @rule(intent=intents)
    def authorize(self, intent):
        model = self._model[intent]
        if model["state"] != "CREATED":
            return
        response = self._client.post(f"/payment_intents/{intent}/authorize", headers=_key())
        assert response.status_code == 200, response.text
        model["authorized"] = model["amount"]
        model["state"] = "AUTHORIZED"

    @rule(intent=intents, raw=integers(min_value=0, max_value=10**9))
    def capture(self, intent, raw):
        model = self._model[intent]
        if model["state"] not in _LEGAL_CAPTURE:
            return
        remaining = model["authorized"] - model["captured"]
        if remaining <= CAPTURE_FEE:
            return
        amount = CAPTURE_FEE + 1 + (raw % (remaining - CAPTURE_FEE))
        response = self._client.post(
            f"/payment_intents/{intent}/capture", json={"amount": amount}, headers=_key()
        )
        assert response.status_code == 200, response.text
        model["captured"] += amount
        model["state"] = (
            "CAPTURED" if model["captured"] == model["authorized"] else "PARTIALLY_CAPTURED"
        )

    @rule(intent=intents, raw=integers(min_value=0, max_value=10**9))
    def refund(self, intent, raw):
        model = self._model[intent]
        if model["state"] not in _LEGAL_REFUND:
            return
        refundable = model["captured"] - model["refunded"]
        if refundable <= 0:
            return
        amount = 1 + (raw % refundable)
        response = self._client.post(
            f"/payment_intents/{intent}/refund", json={"amount": amount}, headers=_key()
        )
        assert response.status_code == 200, response.text
        model["refunded"] += amount
        model["state"] = (
            "REFUNDED" if model["refunded"] == model["captured"] else "PARTIALLY_REFUNDED"
        )

    @rule(intent=intents)
    def void(self, intent):
        model = self._model[intent]
        if model["state"] not in _LEGAL_VOID:
            return
        response = self._client.post(f"/payment_intents/{intent}/void", headers=_key())
        assert response.status_code == 200, response.text
        model["state"] = "VOIDED"

    # -- rules: illegal operations must 409 and change nothing -------------

    @rule(intent=intents)
    def illegal_capture_on_created(self, intent):
        model = self._model[intent]
        if model["state"] != "CREATED":
            return
        response = self._client.post(
            f"/payment_intents/{intent}/capture", json={"amount": 100}, headers=_key()
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "invalid_state"
        self._assert_unchanged(intent)

    @rule(intent=intents)
    def illegal_refund_before_capture(self, intent):
        model = self._model[intent]
        if model["state"] not in {"CREATED", "AUTHORIZED"}:
            return
        response = self._client.post(
            f"/payment_intents/{intent}/refund", json={"amount": 50}, headers=_key()
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "invalid_state"
        self._assert_unchanged(intent)

    def _assert_unchanged(self, intent) -> None:
        model = self._model[intent]
        body = self._client.get(f"/payment_intents/{intent}").json()
        assert body["state"] == model["state"]
        assert body["captured_amount"] == model["captured"]
        assert body["refunded_amount"] == model["refunded"]

    # -- invariants -------------------------------------------------------

    @invariant()
    def inv1_captured_le_authorized(self):
        for intent_id in self._model:
            body = self._client.get(f"/payment_intents/{intent_id}").json()
            assert body["captured_amount"] <= body["authorized_amount"]

    @invariant()
    def inv5_state_matches_legal_table(self):
        for intent_id, model in self._model.items():
            body = self._client.get(f"/payment_intents/{intent_id}").json()
            assert body["state"] == model["state"], (intent_id, body["state"], model["state"])

    @invariant()
    def inv4_ledger_balanced(self):
        assert global_imbalance(self._db_path) == 0


PayFlowMachine.TestCase.settings = settings(
    max_examples=25, stateful_step_count=12, deadline=None
)
TestSanityMachine = PayFlowMachine.TestCase
