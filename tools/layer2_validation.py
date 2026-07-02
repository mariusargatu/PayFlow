"""Layer 2 exit criterion demo: an induced triage judgment regression.

The Phase 5 exit criterion (design section 6.3, roadmap Phase 5): a deliberately
degraded triage verdict must turn Layer 2 red while Layers 0 and 1 stay green,
the layer catches what nothing below it can. This script proves it end to end:

  1. Regression hook off by default: _system() is byte identical to _SYSTEM, and a
     bad_invariant fixture still triages as bad_invariant (not real_bug).
  2. Layers 0 and 1 (uv run demo) stay green even with PAYFLOW_TRIAGE_REGRESSION=1
     set, those layers never call triage, so the biased judgment is invisible to
     them.
  3. The Layer 2 suite is green with the regression OFF (honest baseline)...
  4. ...and RED with PAYFLOW_TRIAGE_REGRESSION=1: the biased triage misclassifies
     every bad_* fixture and both rigged world scenarios as real_bug.

Artifacts (captured output + a machine readable summary the demo reads) land in
agent_runs/<ts>-layer2-validation/. Steps 3 and 4 make real triage calls and cost
a small number of tokens; step 1 makes one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_LAYER2 = [
    sys.executable,
    "-m",
    "pytest",
    "-m",
    "layer2",
    "tests/agent_metamorphic",
    "tests/agent_scenarios",
    "-q",
    "-s",
    "-p",
    "no:cacheprovider",
    "-rf",
]


def _default_behavior_unchanged() -> tuple[bool, str]:
    """Prove the hook is inert when unset: same prompt, same verdict on a bad case."""
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
    os.environ.pop("PAYFLOW_TRIAGE_REGRESSION", None)

    from agent.nodes.triage import _SYSTEM, _system

    if _system() != _SYSTEM:
        return False, "hook changed the system prompt while unset"

    sys.path.insert(0, str(_ROOT / "tests"))
    sys.path.insert(0, str(_ROOT / "tests" / "agent_metamorphic"))
    from _layer2 import CachingTriageRunner
    from fixtures import PARTIAL_CAPTURE_INVARIANT as fx
    from transforms import single_failure_state

    runner = CachingTriageRunner()
    ff = fx.failures[0]
    verdict = runner.verdicts(single_failure_state(fx, ff)).get(ff.ref)
    ok = verdict == ff.expected  # bad_invariant, NOT real_bug
    detail = f"unset triage classified {ff.ref} as {verdict} (expected {ff.expected})"
    return ok, detail


def _run(cmd: list[str], env: dict) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=_ROOT, env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def _cost_from_file(path: Path) -> dict:
    """Sum the per suite cost summaries the triage runner appended (one JSON/line)."""
    if not path.exists():
        return {}
    total = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    model = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        model = entry.get("model", model)
        for field in ("calls", "input_tokens", "output_tokens", "total_tokens"):
            total[field] += entry.get(field, 0)
    total["model"] = model
    return total


def _failed_tests(output: str) -> list[str]:
    return sorted(
        line.split("FAILED ", 1)[1].split(" ")[0].strip()
        for line in output.splitlines()
        if line.startswith("FAILED ")
    )


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = _ROOT / "agent_runs" / f"{stamp}-layer2-validation"
    run_dir.mkdir(parents=True, exist_ok=True)

    print("layer2-validation: step 1 -- regression hook is inert when unset")
    hook_ok, hook_detail = _default_behavior_unchanged()
    print(f"  {'OK' if hook_ok else 'FAIL'}: {hook_detail}")

    base_env = dict(os.environ)
    base_env.pop("PAYFLOW_TRIAGE_REGRESSION", None)
    regression_env = dict(base_env)
    regression_env["PAYFLOW_TRIAGE_REGRESSION"] = "1"

    print("layer2-validation: step 2 -- Layers 0/1 (uv run demo) with regression ON")
    demo_code, demo_out = _run([sys.executable, "-m", "tools.demo"], regression_env)
    (run_dir / "demo_output.txt").write_text(demo_out, encoding="utf-8")
    demo_green = demo_code == 0
    print(f"  demo exit {demo_code} ({'green' if demo_green else 'RED'})")

    print("layer2-validation: step 3 -- Layer 2 suite, regression OFF (baseline)")
    base_cost_file = run_dir / "baseline_cost.jsonl"
    base_env["PAYFLOW_LAYER2_COST_FILE"] = str(base_cost_file)
    base_code, base_out = _run(_LAYER2, base_env)
    (run_dir / "layer2_baseline_output.txt").write_text(base_out, encoding="utf-8")
    baseline_failed = _failed_tests(base_out)
    baseline_green = base_code == 0
    print(f"  layer2 baseline exit {base_code} ({'green' if baseline_green else 'RED'})")

    print("layer2-validation: step 4 -- Layer 2 suite, regression ON")
    reg_cost_file = run_dir / "regression_cost.jsonl"
    regression_env["PAYFLOW_LAYER2_COST_FILE"] = str(reg_cost_file)
    reg_code, reg_out = _run(_LAYER2, regression_env)
    (run_dir / "layer2_regression_output.txt").write_text(reg_out, encoding="utf-8")
    regression_red = reg_code != 0
    regression_failed = _failed_tests(reg_out)
    # Tests the regression newly broke (were green at baseline) are what Layer 2
    # caught that nothing below it can.
    flipped = sorted(set(regression_failed) - set(baseline_failed))
    print(f"  layer2 regression exit {reg_code} ({'RED' if regression_red else 'green'})")
    for name in flipped:
        print(f"    caught (flipped to real_bug): {name}")

    baseline_cost = _cost_from_file(base_cost_file)
    regression_cost = _cost_from_file(reg_cost_file)

    held = hook_ok and demo_green and baseline_green and regression_red and bool(flipped)
    summary_line = (
        f"baseline green, regression caught {len(flipped)} misjudgment(s); "
        f"Layers 0/1 stayed green (last run {stamp})"
        if held
        else f"demonstration did not hold (run {stamp}); see outputs"
    )

    summary = {
        "stamp": stamp,
        "exit_criterion_held": held,
        "hook_inert_when_unset": hook_ok,
        "hook_detail": hook_detail,
        "demo_layers01_green": demo_green,
        "layer2_baseline_green": baseline_green,
        "layer2_baseline_failed": baseline_failed,
        "layer2_regression_red": regression_red,
        "regression_flipped_tests": flipped,
        "baseline_cost": baseline_cost,
        "regression_cost": regression_cost,
        "summary_line": summary_line,
    }
    (run_dir / "layer2_validation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nlayer2-validation: {summary_line}")
    print(f"layer2-validation: artifacts -> {run_dir}")
    return 0 if held else 1


if __name__ == "__main__":
    sys.exit(main())
