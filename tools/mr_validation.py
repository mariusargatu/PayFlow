"""Flagship demo: a bug that only a metamorphic relation can catch.

The seeded bug here is chosen to be INVISIBLE to every single run check and
visible only across two runs. It is an IN PROCESS monkeypatch, with no committed
source change to payflow/:

  On a repeat capture of an intent (captured_amount > 0) the flat platform fee is
  still debited from the merchant, but it is misrouted to `holds` instead of
  `platform_fees`.

Why this is metamorphic only, and not caught by the invariant suite:
  - The merchant is debited the fee on every capture, so the per merchant
    conservation invariant (balance == captures - fees - refunds) stays exact.
  - INV-1/INV-2, non negativity, and the precondition rules never read
    platform_fees; the generated conservation invariant is scoped to merchant
    accounts on purpose (the shared server flake journey entry explains why it
    cannot read the shared system accounts without going flaky).
  - So every single run stays internally consistent. Only MR-1 (split capture),
    which compares the platform_fees delta across a one capture run and a
    two capture run, sees that the second fee never reached platform_fees.

This tool serves the patched PayFlow in process, then:
  1. runs the committed rule/invariant spec  -> must stay GREEN,
  2. runs the committed MR module            -> must go RED (MR-1),
  3. triages the MR failure                  -> must be labeled real_bug.

WARNING: step 3 calls the OpenAI API for triage and costs a few tokens.
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
            if captured > remaining:
                raise svc.ValidationError(
                    f"capture amount {captured} exceeds remaining hold {remaining}"
                )
            fees.validate_capture_amount(captured, self._fee)
            merchant = intent.merchant_account_id
            # SEEDED BUG (metamorphic only): the fee is always debited from the
            # merchant, but on a repeat capture it is credited to holds instead of
            # platform_fees. The pair stays balanced and the merchant is charged
            # correctly, so no single run check notices; only a cross run relation
            # comparing platform_fees deltas can.
            fee_credit = ACCT_PLATFORM_FEES if intent.captured_amount == 0 else ACCT_HOLDS
            self._ledger.write(
                conn,
                [
                    LedgerPair(EntryType.CAPTURE, ACCT_HOLDS, merchant, captured, intent_id),
                    LedgerPair(EntryType.CAPTURE_FEE, merchant, fee_credit, self._fee, intent_id),
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


def _latest_run_report() -> dict | None:
    runs = sorted((_ROOT / "agent_runs").glob("*/report.json"))
    scored = [
        p
        for p in runs
        if "offline" not in p.parent.name
        and "triage" not in p.parent.name
        and "mr-validation" not in p.parent.name
    ]
    if not scored:
        return None
    return json.loads(scored[-1].read_text(encoding="utf-8"))


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
    from agent.schemas import Invariant, MetamorphicRelation, Rule

    spec_path = _ROOT / "generated_specs" / "payflow_spec.py"
    mr_path = _ROOT / "generated_specs" / "payflow_mr.py"
    if not spec_path.exists() or not mr_path.exists():
        print("mr-validation: missing committed generated specs; run `uv run agent-run` first")
        return 2

    report = _latest_run_report()
    proposed_rules = [Rule(**r) for r in report.get("proposed_rules", [])] if report else []
    proposed_invariants = (
        [Invariant(**i) for i in report.get("proposed_invariants", [])] if report else []
    )
    proposed_relations = (
        [MetamorphicRelation(**r) for r in report.get("proposed_relations", [])] if report else []
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

    with tempfile.TemporaryDirectory(prefix="payflow_mr_") as tmp:
        server, base_url = _serve(str(Path(tmp) / "patched.db"), config.capture_fee)
        print(f"mr-validation: patched PayFlow (fee misrouted on repeat capture) at {base_url}")

        # 1. The rule/invariant spec must stay green: no single run sees the bug.
        rules_state = {"sut_base_url": base_url, "generated_spec_path": str(spec_path)}
        rules_state.update(execute(rules_state, deps))
        rules_result = rules_state["hypothesis_results"]

        # 2. The MR module must go red. Run it alone through the same execute node.
        mr_state = {"sut_base_url": base_url, "generated_spec_path": str(mr_path)}
        mr_state.update(execute(mr_state, deps))
        mr_result = mr_state["hypothesis_results"]
        server.should_exit = True

    print(f"mr-validation: rule/invariant spec passed = {rules_result.passed}")
    print(f"mr-validation: MR module passed = {mr_result.passed}")

    if not rules_result.passed:
        print("mr-validation: FAILED, the invariant suite went red; the bug is not MR only")
        for f in rules_result.failures:
            print(f"  {f.tag()}: {f.message}")
        return 1
    if mr_result.passed:
        print("mr-validation: FAILED, the MR module stayed green; the bug was not caught")
        return 1

    # 3. Triage the relation failure: it must be a real_bug, not a bad relation.
    triage_state = {
        "hypothesis_results": mr_result,
        "proposed_rules": proposed_rules,
        "proposed_invariants": proposed_invariants,
        "proposed_relations": proposed_relations,
    }
    triage_state.update(triage(triage_state, deps))
    verdicts = triage_state["triaged_failures"]
    real = sum(1 for v in verdicts if v.classification == "real_bug")
    accuracy = real / len(verdicts) if verdicts else 0.0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = _ROOT / "agent_runs" / f"{stamp}-mr-validation"
    write_report(triage_state, deps, str(run_dir))
    extra = {
        "seeded_bug": "flat fee misrouted to holds on repeat captures (in process)",
        "ground_truth": "real_bug (platform_fees under-credited across runs)",
        "invariant_suite_passed": rules_result.passed,
        "mr_module_passed": mr_result.passed,
        "mr_failures": [f.tag() for f in mr_result.failures],
        "mr_failure_messages": [f.message for f in mr_result.failures],
        "verdicts": [v.model_dump() for v in verdicts],
        "verdict_accuracy": accuracy,
        "cost": budget.summary(config.model),
    }
    (run_dir / "mr_validation.json").write_text(json.dumps(extra, indent=2), encoding="utf-8")

    print("\nmr-validation: the invariant suite stayed GREEN; only the MR module caught the bug")
    print(f"mr-validation: MR failures {[f.tag() for f in mr_result.failures]}")
    for f in mr_result.failures:
        print(f"  {f.tag()}: {f.message}")
    print("\nmr-validation: triage verdicts")
    for v in verdicts:
        print(f"  {v.failure_ref} -> {v.classification} ({v.target}): {v.reasoning[:140]}")
    print(f"mr-validation: verdict accuracy {accuracy:.0%} ({real}/{len(verdicts)} labeled real_bug)")
    print(f"mr-validation: artifacts -> {run_dir}")
    return 0 if (accuracy == 1.0 and not mr_result.passed) else 1


if __name__ == "__main__":
    sys.exit(main())
