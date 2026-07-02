"""Run B: triage ground truth against a deliberately broken PayFlow.

The seeded fm_a/fm_c toggles are invisible to sequential runs (design section
5.9), so this tool breaks PayFlow a third way that a sequential agent run can
see: it drops the INV-1 precondition so a capture can exceed authorization. The
break is an IN PROCESS monkeypatch applied here, with no committed source change
to payflow/:

1. strip the payment_intents CHECK constraints (captured<=authorized,
   refunded<=captured) from the schema, so the over capture can persist;
2. replace PaymentService.capture with a copy that omits the "capture amount
   exceeds remaining hold" guard.

PayFlow is then served in process on a free port and the agent's execute + triage
nodes run against it. The seeded break is the ground truth label: triage must
classify the resulting failures as real_bug. Verdict accuracy is recorded.

WARNING: this calls the OpenAI API for triage and costs a few tokens.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _apply_monkeypatch() -> None:
    import payflow.infrastructure.db as dbmod

    dbmod._SCHEMA = dbmod._SCHEMA.replace(
        "    created_at TEXT NOT NULL,\n"
        "    CHECK (captured_amount <= authorized_amount),\n"
        "    CHECK (refunded_amount <= captured_amount)\n",
        "    created_at TEXT NOT NULL\n",
    )
    assert "captured_amount <= authorized_amount" not in dbmod._SCHEMA, "schema strip failed"

    from payflow.domain import fees
    from payflow.domain import service as svc
    from payflow.domain import state_machine as sm
    from payflow.domain.models import (
        ACCT_HOLDS,
        ACCT_PLATFORM_FEES,
        EntryType,
        LedgerPair,
    )

    def patched_capture(self, key, intent_id, amount):
        if amount is not None:
            svc._require_positive(amount, "amount")

        def op(conn):
            intent = self._load_intent(conn, intent_id)
            sm.check_capture(intent)
            remaining = intent.authorized_amount - intent.captured_amount
            captured = amount if amount is not None else remaining
            svc._require_positive(captured, "capture amount")
            # DROPPED (the INV-1 precondition):
            #   if captured > remaining: raise ValidationError(...)
            fees.validate_capture_amount(captured, self._fee)
            merchant = intent.merchant_account_id
            self._ledger.write(
                conn,
                [
                    LedgerPair(EntryType.CAPTURE, ACCT_HOLDS, merchant, captured, intent_id),
                    LedgerPair(EntryType.CAPTURE_FEE, merchant, ACCT_PLATFORM_FEES, self._fee, intent_id),
                ],
            )
            total = intent.captured_amount + captured
            updated = intent.with_changes(
                captured_amount=total,
                state=sm.state_after_capture(intent.authorized_amount, total),
            )
            self._intents.save(conn, updated)
            return svc.OperationResult(200, svc._intent_body(updated))

        return self._idempotency.run(
            key, "POST /payment_intents/capture", {"id": intent_id, "amount": amount}, op
        )

    svc.PaymentService.capture = patched_capture


def _serve(db_path: str, capture_fee: int):
    import uvicorn

    from payflow.api.app import create_app
    from payflow.config import Config

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    app = create_app(Config(db_path=db_path, capture_fee=capture_fee, bug=None))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()

    import httpx

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/openapi.json", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    return server, base_url


def main() -> int:
    import tempfile

    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
    os.environ.setdefault("PAYFLOW_DB_PATH", str(Path(tempfile.mkdtemp()) / "import.db"))

    _apply_monkeypatch()

    from agent.budget import CostGuard
    from agent.config import AgentConfig
    from agent.graph import AgentDeps
    from agent.llm import LLMClient
    from agent.nodes.execute import execute
    from agent.nodes.report import write_report
    from agent.nodes.triage import triage
    from agent.schemas import Invariant, Rule

    spec_path = _ROOT / "generated_specs" / "payflow_spec.py"
    if not spec_path.exists():
        print("triage-validation: no committed generated spec; run `uv run agent-run` first")
        return 2

    report_a = _latest_run_report()
    proposed_rules = [Rule(**r) for r in report_a.get("proposed_rules", [])] if report_a else []
    proposed_invariants = (
        [Invariant(**i) for i in report_a.get("proposed_invariants", [])] if report_a else []
    )

    config = AgentConfig.from_env()
    budget = CostGuard.from_env()
    deps = AgentDeps(
        config=config,
        budget=budget,
        llm=LLMClient(config, budget),
        offline=False,
        generated_spec_path=str(spec_path),
    )

    with tempfile.TemporaryDirectory(prefix="payflow_triage_") as tmp:
        server, base_url = _serve(str(Path(tmp) / "patched.db"), config.capture_fee)
        print(f"triage-validation: broken PayFlow (INV-1 precondition dropped) at {base_url}")
        # Widen the Hypothesis search so the over capture path is reliably
        # reached (examples cost time, not tokens; the committed replay slice
        # stays at its modest default).
        os.environ["PAYFLOW_SPEC_MAX_EXAMPLES"] = "150"
        state = {
            "sut_base_url": base_url,
            "generated_spec_path": str(spec_path),
            "proposed_rules": proposed_rules,
            "proposed_invariants": proposed_invariants,
        }
        state.update(execute(state, deps))
        server.should_exit = True

    result = state["hypothesis_results"]
    if result.passed:
        print("triage-validation: FAILED, the broken build produced no failures to triage")
        return 1

    state.update(triage(state, deps))
    verdicts = state["triaged_failures"]
    real = sum(1 for v in verdicts if v.classification == "real_bug")
    accuracy = real / len(verdicts) if verdicts else 0.0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = _ROOT / "agent_runs" / f"{stamp}-triage-validation"
    write_report(state, deps, str(run_dir))
    extra = {
        "ground_truth": "real_bug (INV-1 precondition dropped in process)",
        "failures_seen": [f.tag() for f in result.failures],
        "verdicts": [v.model_dump() for v in verdicts],
        "verdict_accuracy": accuracy,
        "cost": budget.summary(config.model),
    }
    (run_dir / "triage_validation.json").write_text(json.dumps(extra, indent=2), encoding="utf-8")

    print(f"\ntriage-validation: failures {[f.tag() for f in result.failures]}")
    for v in verdicts:
        print(f"  {v.failure_ref} -> {v.classification} ({v.target}): {v.reasoning[:120]}")
    print(f"triage-validation: verdict accuracy {accuracy:.0%} ({real}/{len(verdicts)} labeled real_bug)")
    print(f"triage-validation: artifacts -> {run_dir}")
    return 0 if accuracy == 1.0 else 1


def _latest_run_report() -> dict | None:
    runs = sorted((_ROOT / "agent_runs").glob("*/report.json"))
    scored = [p for p in runs if "offline" not in p.parent.name and "triage" not in p.parent.name]
    if not scored:
        return None
    return json.loads(scored[-1].read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.exit(main())
