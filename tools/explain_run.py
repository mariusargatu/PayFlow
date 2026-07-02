"""explain-run: replay a finished agent run as a visual summary.

    uv run explain-run              # the most recent run under agent_runs/
    uv run explain-run latest       # same
    uv run explain-run <timestamp>  # a specific run dir (prefix match is fine)

Reads the run's report.json and renders the pipeline path, the discovery funnel,
triage verdicts, and cost. Deterministic and free: it reads artifacts, it does
not call the agent or the LLM.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console

from .run_view import render_report

_ROOT = Path(__file__).resolve().parents[1]
_RUNS = _ROOT / "agent_runs"


def _resolve(selector: str) -> Path | None:
    runs = sorted(p for p in _RUNS.glob("*/") if (p / "report.json").exists())
    if not runs:
        return None
    if selector in ("", "latest"):
        return runs[-1]
    matches = [p for p in runs if p.name.startswith(selector) or selector in p.name]
    return matches[-1] if matches else None


def main() -> int:
    console = Console()
    if not _RUNS.exists():
        console.print("[red]no agent_runs/ directory; run `uv run agent-run` first[/red]")
        return 1
    selector = sys.argv[1] if len(sys.argv) > 1 else "latest"
    run_dir = _resolve(selector)
    if run_dir is None:
        console.print(f"[red]no run found for {selector!r} under {_RUNS}[/red]")
        return 1
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    console.print(f"[grey58]run:[/grey58] {run_dir.name}")
    render_report(report, console)
    return 0


if __name__ == "__main__":
    sys.exit(main())
