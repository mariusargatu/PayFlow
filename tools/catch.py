"""`uv run catch`: watch the verification pyramid catch bad agent code.

`uv run demo` is all green, which paradoxically shows the opposite of this repo's
thesis. This command is the payoff: it seeds three real bugs into the payment
core, one per demonstration, and shows a verification layer catch each one in
red with the exact evidence, then restores a pristine tree. Keyless by design:
pure local subprocess orchestration, no LLM calls, no network, no API keys.

Three demonstrations, each self contained and each cleaned up in a finally:

  1. FM-B  ->  Layer 0 (import-linter): an admin route writes ledger rows
     straight from the API layer, bypassing the domain. The static layering gate
     catches it deterministically. This is the guaranteed anchor.
  2. FM-A  ->  the concurrency harness: check then act idempotency lets a
     duplicate capture slip through under load. Best effort, environment
     sensitive, presented honestly as an xfail when the race does not surface.
  3. FM-C  ->  Layer 1 atomicity (INV-4): the capture ledger pairs commit
     separately, so a concurrent snapshot catches a transient imbalance. Best
     effort, same honest framing.

Exit 0 when the demo runs (a catch is the expected, successful outcome). Exit
nonzero only when the Layer 0 anchor fails to catch FM-B, which is a real
regression worth surfacing. The seeded bugs live in specs/constraints.md and the
FM-B module toggle mirrors tools/seeded_bugs/activate_fm_b.sh.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ADMIN_SRC = _ROOT / "tools" / "seeded_bugs" / "fm_b_admin.py"
_ADMIN_DST = _ROOT / "payflow" / "api" / "admin.py"

_TEST_FILE = "tests/concurrency/test_idempotent_replay.py"
_FM_A_NODE = f"{_TEST_FILE}::test_fm_a_race_is_observable"
_FM_C_NODE = f"{_TEST_FILE}::test_fm_c_atomicity_violation_observable"
_PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rA"]

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _run(cmd: list[str]) -> tuple[int, str, float]:
    start = time.perf_counter()
    proc = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr, time.perf_counter() - start


def _hr() -> None:
    print(f"{CYAN}{'=' * 74}{RESET}")


def _section(number: int, title: str, subtitle: str) -> None:
    print()
    print(f"{BOLD}{YELLOW}Demo {number}/3   {title}{RESET}")
    print(f"{DIM}  {subtitle}{RESET}")


def _grep(output: str, needle: str) -> str:
    for line in output.splitlines():
        if needle in line:
            return line.strip()
    return ""


# -- Layer 0 output parsing -------------------------------------------------


def _broken_count(output: str) -> int:
    match = re.search(r"Contracts: \d+ kept, (\d+) broken", output)
    return int(match.group(1)) if match else 0


def _broken_contract(output: str) -> str:
    match = re.search(r"^(.*) BROKEN$", output, re.MULTILINE)
    return match.group(1).strip() if match else "unknown contract"


def _offending_imports(output: str) -> list[str]:
    """The exact api -> infrastructure dependency lines import-linter reports."""
    return [
        line.strip().lstrip("- ").strip()
        for line in output.splitlines()
        if "->" in line and "payflow.api" in line and "payflow.infrastructure" in line
    ]


# -- concurrency probe parsing ----------------------------------------------


def _verdict_line(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("PASSED "):
            return line.strip()
    return ""


def _xfail_reason(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("XFAIL"):
            after = line.split("::", 1)[-1]
            parts = after.split(" ", 1)
            return parts[1].strip() if len(parts) > 1 else after.strip()
    return "the violation did not surface in this run (environment sensitive)"


# -- the three demonstrations -----------------------------------------------


def _demo_fm_b() -> str:
    _section(
        1,
        "FM-B  ->  Layer 0 (import-linter)",
        "an admin route writes ledger rows straight from the API layer, bypassing the domain",
    )
    try:
        shutil.copyfile(_ADMIN_SRC, _ADMIN_DST)
        print(f"{DIM}  seeded: payflow/api/admin.py now reaches into payflow.infrastructure{RESET}")
        returncode, output, elapsed = _run(["lint-imports"])
        if returncode != 0 and _broken_count(output) > 0:
            print(f"{BOLD}{RED}  CAUGHT by Layer 0 in {elapsed:.2f}s{RESET}")
            print(f"{RED}  contract broken: {_broken_contract(output)}{RESET}")
            for offender in _offending_imports(output):
                print(f"{RED}    {offender}{RESET}")
            return "caught"
        print(f"{BOLD}{RED}  REGRESSION: Layer 0 did NOT catch FM-B (this should never happen){RESET}")
        print(f"{DIM}" + "\n".join(output.strip().splitlines()[-8:]) + f"{RESET}")
        return "MISSED"
    finally:
        _ADMIN_DST.unlink(missing_ok=True)
        print(f"{DIM}  restored: payflow/api/admin.py removed, tree pristine{RESET}")


def _probe(number: int, title: str, subtitle: str, node: str, layer: str,
           meaning: str, corroborate: str | None) -> str:
    _section(number, title, subtitle)
    print(f"{DIM}  running the repo's own concurrency test ...{RESET}")
    _, output, elapsed = _run(_PYTEST + [node])
    if re.search(r"\b(\d+) passed", output):
        print(f"{BOLD}{RED}  CAUGHT by the {layer} in {elapsed:.2f}s{RESET}")
        verdict = _verdict_line(output)
        if verdict:
            print(f"{RED}  {verdict}{RESET}")
        print(f"{RED}  meaning: {meaning}{RESET}")
        if corroborate:
            logged = _grep(output, corroborate)
            if logged:
                print(f"{DIM}  server logged: {logged}{RESET}")
        return "caught"
    if re.search(r"\b(\d+) xfailed", output):
        print(f"{BOLD}{YELLOW}  not reproduced this run ({elapsed:.2f}s){RESET}")
        print(f"{DIM}  {_xfail_reason(output)}{RESET}")
        print(f"{DIM}  honest xfail: this catch is environment sensitive, never a silent pass{RESET}")
        return "not-reproduced"
    print(f"{BOLD}{YELLOW}  inconclusive ({elapsed:.2f}s){RESET}")
    return "error"


def _segment(layer: str, bug: str, status: str) -> str:
    if status == "caught":
        return f"{layer} caught {bug} {GREEN}✓{RESET}"
    if status == "not-reproduced":
        return f"{layer} + {bug} not reproduced {YELLOW}~{RESET}"
    if status == "MISSED":
        return f"{layer} MISSED {bug} {RED}✗{RESET}"
    return f"{layer} + {bug} inconclusive {YELLOW}?{RESET}"


def main() -> int:
    _hr()
    print(f"{BOLD}{CYAN}  uv run catch{RESET}{DIM}   watch the pyramid catch bad agent code{RESET}")
    print(f"{DIM}  three seeded bugs, three layers, each caught in red then cleaned up{RESET}")
    _hr()

    fm_b = _demo_fm_b()
    fm_a = _probe(
        2,
        "FM-A  ->  the concurrency harness",
        "check then act idempotency lets a duplicate capture slip through under load",
        _FM_A_NODE,
        "concurrency harness",
        "the same Idempotency-Key was captured more than once",
        corroborate="UNIQUE constraint failed",
    )
    fm_c = _probe(
        3,
        "FM-C  ->  Layer 1 atomicity (INV-4)",
        "the capture ledger pairs commit separately, so a snapshot catches a transient imbalance",
        _FM_C_NODE,
        "Layer 1 atomicity check",
        "a concurrent snapshot caught debits not equal to credits, violating INV-4",
        corroborate=None,
    )

    # Defensive: guarantee the seeded module never survives the run.
    if _ADMIN_DST.exists():
        _ADMIN_DST.unlink()

    print()
    _hr()
    segments = [
        _segment("Layer 0", "FM-B", fm_b),
        _segment("concurrency", "FM-A", fm_a),
        _segment("Layer 1", "FM-C", fm_c),
    ]
    print(f"{BOLD}  scorecard:{RESET}  " + "    ".join(segments))

    if fm_b == "caught":
        caught = sum(1 for s in (fm_b, fm_a, fm_c) if s == "caught")
        print(f"{BOLD}{GREEN}  VERDICT: the pyramid caught {caught}/3 seeded bugs. "
              f"tree restored, nothing left behind.{RESET}")
        _hr()
        return 0
    print(f"{BOLD}{RED}  VERDICT: Layer 0 failed to catch FM-B, a real regression to investigate.{RESET}")
    _hr()
    return 1


if __name__ == "__main__":
    sys.exit(main())
