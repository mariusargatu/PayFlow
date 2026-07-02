"""`uv run demo`: run the fast Phase 1 gates and render a one screen summary.

Each layer that exists runs; layers that land later print their phase. The exit
code is nonzero if any gate failed, so the same command works in a terminal and
in CI. Kept dependency free on purpose: ANSI colors, no extra packages.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MUTATION_BASELINE = _ROOT / "mutation" / "baseline.json"

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

_PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
_REPLAY_A = (
    "tests/concurrency/test_idempotent_replay.py::test_replay_correct_build_single_effect"
)


def _pytest_count(output: str) -> str:
    parts = []
    for label, pattern in (("passed", r"(\d+) passed"), ("xfailed", r"(\d+) xfailed"), ("failed", r"(\d+) failed")):
        match = re.search(pattern, output)
        if match:
            parts.append(f"{match.group(1)} {label}")
    return ", ".join(parts) or "no tests"


def _contracts_count(output: str) -> str:
    match = re.search(r"Contracts: (\d+) kept, (\d+) broken", output)
    return f"{match.group(1)} kept, {match.group(2)} broken" if match else "unknown"


GATES = (
    ("Layer 0", "import contracts", ["lint-imports"], _contracts_count),
    ("Drift", "state machine diagram", _PYTEST + ["tests/drift/test_state_machine_diagram.py"], _pytest_count),
    ("Drift", "importlinter snapshot", _PYTEST + ["tests/drift/test_importlinter_contracts.py"], _pytest_count),
    ("Drift", "agent graph diagram", _PYTEST + ["tests/drift/test_agent_graph_diagram.py"], _pytest_count),
    ("Layer 1", "property sanity machine", _PYTEST + ["tests/property"], _pytest_count),
    ("Layer 1", "idempotent replay (concurrency A)", _PYTEST + [_REPLAY_A], _pytest_count),
)

def _layer3_note() -> str:
    """Read the committed mutation baseline; never runs mutmut (kept fast)."""
    if not _MUTATION_BASELINE.exists():
        return "no baseline yet (uv run python mutation/run_baseline.py)"
    try:
        headline = json.loads(_MUTATION_BASELINE.read_text())["runs"]["headline"]
    except (json.JSONDecodeError, KeyError):
        return "baseline unreadable"
    return (
        f"baseline {headline['kill_rate_pct']}% kill rate, zero hand-written tests "
        f"(nightly recomputes)"
    )


def _layer2_note() -> str:
    """Read the committed last layer2-validation summary; never calls an LLM."""
    runs = sorted((_ROOT / "agent_runs").glob("*-layer2-validation/layer2_validation.json"))
    if not runs:
        return "manual, costs tokens (uv run pytest -m layer2)"
    try:
        summary = json.loads(runs[-1].read_text())["summary_line"]
    except (json.JSONDecodeError, KeyError):
        return "manual, costs tokens (uv run pytest -m layer2)"
    return f"manual (uv run pytest -m layer2); last: {summary}"


def _later_gates() -> tuple:
    return (
        ("Layer 1", "discovery agent (uv run agent-run)", "manual, costs tokens"),
        ("Layer 2", "agent judgment (scenario + AGENT-MR)", _layer2_note()),
        ("Layer 3", "mutation ground truth (mutmut)", _layer3_note()),
    )


def _run(cmd: list[str]) -> tuple[bool, str, float]:
    start = time.perf_counter()
    proc = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    return proc.returncode == 0, proc.stdout + proc.stderr, elapsed


def _status(ok: bool) -> str:
    color = GREEN if ok else RED
    word = "PASS" if ok else "FAIL"
    return f"{color}{word:6}{RESET}"


def main() -> int:
    print(f"\n{BOLD}PayFlow demo: the fast gates{RESET}")
    print(f"{DIM}{'layer':8} {'gate':38} {'result':6} {'detail':22} elapsed{RESET}")

    failures = 0
    total_elapsed = 0.0
    for layer, name, cmd, counter in GATES:
        ok, output, elapsed = _run(cmd)
        total_elapsed += elapsed
        failures += 0 if ok else 1
        detail = counter(output)
        print(f"{layer:8} {name:38} {_status(ok)} {detail:22} {elapsed:6.2f}s")
        if not ok:
            tail = "\n".join(output.strip().splitlines()[-12:])
            print(f"{DIM}{tail}{RESET}")

    for layer, name, note in _later_gates():
        print(f"{DIM}{layer:8} {name:38} {'----':6} {note}{RESET}")

    print()
    if failures:
        print(f"{RED}{BOLD}VERDICT: {failures} gate(s) failed{RESET} "
              f"({total_elapsed:.2f}s total)")
        return 1
    print(f"{GREEN}{BOLD}VERDICT: all gates green{RESET} "
          f"({total_elapsed:.2f}s total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
