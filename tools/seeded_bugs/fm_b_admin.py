"""Seeded bug FM-B (specs/constraints.md): a layering violation, quarantined by default.

This module is the realistic broken version of the layering rule in
specs/constraints.md: an admin route that reaches into
``payflow.infrastructure`` from the API layer and writes ledger entries
directly, bypassing ``payflow.domain`` validation.

Because Layer 0 (import-linter) is a *static* check, the violation only exists
if this module is importable. It therefore lives outside the ``payflow`` tree.

Activation (build time inclusion, never merged):

    tools/seeded_bugs/activate_fm_b.sh     # copies this to payflow/api/admin.py
    uv run lint-imports                     # now fails: api -> infrastructure
    tools/seeded_bugs/deactivate_fm_b.sh   # removes payflow/api/admin.py
"""

from __future__ import annotations

from fastapi import APIRouter, Request

# The violation: the API layer importing infrastructure directly, then writing
# ledger rows without going through payflow.domain.
from payflow.domain.models import ACCT_HOLDS, EntryType
from payflow.domain.seams import UuidIdGenerator
from payflow.infrastructure import intents as intents_sql
from payflow.infrastructure.db import Database
from payflow.infrastructure.ledger.core import CorrectLedgerWriter

admin_router = APIRouter()


@admin_router.post(
    "/admin/payment_intents/{intent_id}/force_capture",
    operationId="forceCapturePaymentIntent",
    summary="Force-capture an intent, bypassing domain validation (FM-B)",
)
def force_capture(request: Request, intent_id: str, amount: int) -> dict:
    config = request.app.state.config
    db = Database(config.db_path)
    ids = UuidIdGenerator()
    ledger = CorrectLedgerWriter()
    with db.transaction() as conn:
        intent = intents_sql.get(conn, intent_id)
        pair_id = ids.ledger_id()
        base = {
            "pair_id": pair_id,
            "entry_type": EntryType.CAPTURE.value,
            "payment_intent_id": intent_id,
            "amount": amount,
            "created_at": "",
        }
        ledger.write(
            conn,
            [
                {"posting_id": f"{pair_id}_d", "account_id": ACCT_HOLDS, "direction": "debit", **base},
                {"posting_id": f"{pair_id}_c", "account_id": intent["merchant_account_id"], "direction": "credit", **base},
            ],
        )
    return {"id": intent_id, "forced_capture": amount}
