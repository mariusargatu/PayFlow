"""`uv run full`: run the whole verification pyramid end to end, always live.

Steps run in order. A step that needs an API key prints a message and is skipped
(not failed) when the key is absent, so the free lanes still complete. Every
step's outcome is collected into one summary at the end. This is a convenience
runner, not a gate: it never replaces `demo` (the blocking fast gates) in CI, and
it does not change the authoritative artifacts beyond what each underlying command
already writes.

    uv run full     # discovery -> fast gates -> Layer 2 -> mutation -> semantic -> report

Slow: the mutation baseline is minutes. Discovery and Layer 2 cost OpenAI tokens
(skipped with a message when OPENAI_API_KEY is unset).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _run(label: str, argv: list[str], needs_key: bool = False) -> tuple[str, str, float]:
    if needs_key and not os.environ.get("OPENAI_API_KEY"):
        print(f"\n=== {label}: SKIPPED (no OPENAI_API_KEY) ===")
        return (label, "skipped", 0.0)
    print(f"\n=== {label} ===", flush=True)
    start = time.perf_counter()
    rc = subprocess.run(argv, cwd=str(_ROOT)).returncode
    return (label, "ok" if rc == 0 else "FAILED", time.perf_counter() - start)


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
    py = sys.executable

    steps = [
        _run("discovery (agent-run)", ["agent-run"]),  # self-skips on no key
        _run("fast gates (demo, Layers 0+1)", ["demo"]),
        _run("Layer 2 (agent judgment)", [py, "-m", "pytest", "-m", "layer2", "-q"], needs_key=True),
        _run("Layer 3 mutation baseline", [py, "mutation/run_baseline.py"]),
        _run("semantic explorer (informational)", [py, "-m", "mutation.semantic.explorer"]),
        _run("trust report", ["build-report"]),
    ]

    print("\n" + "=" * 60)
    print("full pipeline summary:")
    failed = 0
    for label, status, elapsed in steps:
        mark = {"ok": "  ok  ", "skipped": " skip ", "FAILED": "FAILED"}[status]
        print(f"  [{mark}] {label} ({elapsed:.1f}s)")
        failed |= status == "FAILED"
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
