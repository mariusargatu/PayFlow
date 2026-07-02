"""Recompute the Layer 3 mutation baseline (design §11.1).

Runs mutmut twice against the payment core (payflow/domain + the ledger core,
the scope fixed in ADR-0001):

  headline  agent discovered suites only, replayed in process  -> the README claim
  full      the agent suites PLUS the Phase 1 hand written sanity machine

Both numbers land in mutation/baseline.json and mutation/baseline.txt, with each
run's surviving mutants in mutation/survivors.txt. This is the nightly recompute;
the committed artifacts are what the trust report and README read so the repo
shows a real number without anyone running mutmut.

The headline is the honest "zero hand written tests" figure. Kill rate is
reported over covered mutants (killed / (killed + survived)); mutants with no
covering test (paths a suite never exercises, e.g. the seeded bug variants) are
reported separately, never folded into the denominator to flatter the number.

Usage:
    uv run python mutation/run_baseline.py            # both runs, writes artifacts
    uv run python mutation/run_baseline.py --headline # headline run only
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MUT_DIR = _ROOT / "mutation"
_MUTANTS = _ROOT / "mutants"

SCOPE = ["payflow/domain", "payflow/infrastructure/ledger/core.py"]


def _mutmut(*args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "mutmut", *args],
        cwd=str(_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


def _survivors() -> list[str]:
    """Names + status of every non killed mutant (mutmut results)."""
    proc = _mutmut("results", env=dict(os.environ))
    lines = []
    for raw in proc.stdout.splitlines():
        stripped = raw.strip()
        if ": " in stripped and not stripped.startswith("To "):
            lines.append(stripped)
    return sorted(lines)


def _run_one(label: str, full: bool) -> dict:
    env = dict(os.environ)
    if full:
        env["PAYFLOW_MUT_FULL"] = "1"
    else:
        env.pop("PAYFLOW_MUT_FULL", None)

    if _MUTANTS.exists():
        shutil.rmtree(_MUTANTS)

    print(f"[{label}] running mutmut (full={full}) ...", flush=True)
    start = time.perf_counter()
    run = _mutmut("run", env=env)
    elapsed = time.perf_counter() - start
    # mutmut exits non zero when mutants survive; that is data, not an error. A
    # missing stats file is the real failure mode.
    _mutmut("export-cicd-stats", env=env)
    stats_path = _MUTANTS / "mutmut-cicd-stats.json"
    if not stats_path.exists():
        print(run.stdout[-2000:])
        print(run.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"[{label}] mutmut produced no stats; see output above")

    stats = json.loads(stats_path.read_text())
    survivors = _survivors()
    # A timeout is a detection: with shrinking disabled a real failure fails fast,
    # so a mutant that still exhausts the CPU budget made the code loop, which the
    # suite caught. Count it with killed; report it separately for transparency.
    detected = stats["killed"] + stats["timeout"]
    covered = detected + stats["survived"]
    kill_rate = detected / covered if covered else 0.0
    result = {
        "label": label,
        "killed": stats["killed"],
        "timeout_detected": stats["timeout"],
        "detected": detected,
        "survived": stats["survived"],
        "no_tests": stats["no_tests"],
        "suspicious": stats["suspicious"],
        "skipped": stats["skipped"],
        "total": stats["total"],
        "covered": covered,
        "kill_rate": round(kill_rate, 4),
        "kill_rate_pct": round(kill_rate * 100, 1),
        "runtime_seconds": round(elapsed, 1),
        "survivors": survivors,
    }
    print(
        f"[{label}] kill rate {result['kill_rate_pct']}% "
        f"({detected}/{covered} covered; {stats['no_tests']} no-test; "
        f"{elapsed:.0f}s)",
        flush=True,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Recompute the mutation baseline")
    parser.add_argument("--headline", action="store_true", help="headline run only")
    args = parser.parse_args()

    runs = {"headline": _run_one("headline", full=False)}
    if not args.headline:
        runs["full"] = _run_one("full", full=True)

    baseline = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": _tool_version(),
        "scope": SCOPE,
        "hypothesis_budget": {
            "spec_max_examples": int(os.environ.get("PAYFLOW_SPEC_MAX_EXAMPLES", "25")),
            "spec_step_count": int(os.environ.get("PAYFLOW_SPEC_STEP_COUNT", "14")),
            "mr_max_examples": int(os.environ.get("PAYFLOW_MR_MAX_EXAMPLES", "10")),
        },
        "runs": {k: {kk: vv for kk, vv in v.items() if kk != "survivors"} for k, v in runs.items()},
    }
    (_MUT_DIR / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
    (_MUT_DIR / "baseline.txt").write_text(_render_txt(baseline))
    (_MUT_DIR / "survivors.txt").write_text(_render_survivors(runs))
    print(f"\nwrote {_MUT_DIR / 'baseline.json'}")
    return 0


def _tool_version() -> str:
    try:
        import mutmut

        return f"mutmut {mutmut.__version__}"
    except Exception:  # pragma: no cover
        return "mutmut"


def _render_txt(baseline: dict) -> str:
    lines = [
        "PayFlow Layer 3 mutation baseline",
        f"generated: {baseline['generated_at']}  tool: {baseline['tool']}",
        f"scope: {', '.join(baseline['scope'])}",
        "",
    ]
    for name, r in baseline["runs"].items():
        lines += [
            f"[{name}] {r['kill_rate_pct']}% kill rate",
            f"    detected {r['detected']} (killed {r['killed']} + timeout {r['timeout_detected']})  "
            f"survived {r['survived']}  (covered {r['covered']}; rate = detected / covered)",
            f"    no-test {r['no_tests']}  suspicious {r['suspicious']}  "
            f"total generated {r['total']}",
            f"    runtime {r['runtime_seconds']}s",
            "",
        ]
    return "\n".join(lines)


def _render_survivors(runs: dict) -> str:
    lines = ["Surviving (and no-test / suspicious) mutants per run", ""]
    for name, r in runs.items():
        lines.append(f"=== {name} ===")
        lines += (r["survivors"] or ["    (none)"])
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
