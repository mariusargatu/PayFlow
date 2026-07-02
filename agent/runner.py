"""agent-run entry point.

Starts a fresh PayFlow on a free port with a temporary SQLite database, runs the
property generation graph against it, and writes artifacts under
``agent_runs/<timestamp>/``. Loads ``.env`` for the OpenAI key; the key is never
printed or logged. A budget exceeded run still leaves a partial report behind.

WARNING: a non offline run calls the OpenAI API and costs tokens. Use --offline
to exercise the deterministic pipeline (compile, execute, report) for free.
"""

from __future__ import annotations

import argparse
import contextlib
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

from .budget import BudgetExceeded, CostGuard
from .config import AgentConfig
from .graph import AgentDeps, build_graph
from .llm import LLMClient
from .nodes.report import write_report

_ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class LiveServer:
    process: subprocess.Popen
    base_url: str


@contextlib.contextmanager
def live_payflow(db_path: str, bug: str | None, capture_fee: int):
    import os

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = dict(os.environ)
    env["PAYFLOW_DB_PATH"] = db_path
    env["PAYFLOW_CAPTURE_FEE"] = str(capture_fee)
    env.pop("PAYFLOW_BUG", None)
    if bug:
        env["PAYFLOW_BUG"] = bug
    cmd = [
        sys.executable, "-m", "uvicorn", "payflow.api.app:app",
        "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
    ]
    process = subprocess.Popen(cmd, env=env, cwd=str(_ROOT))
    try:
        _await_ready(base_url, process)
        yield LiveServer(process=process, base_url=base_url)
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10)
        if process.poll() is None:
            process.kill()


def _await_ready(base_url: str, process: subprocess.Popen, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"PayFlow exited early with code {process.returncode}")
        try:
            if httpx.get(f"{base_url}/openapi.json", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.05)
    raise RuntimeError("PayFlow did not become ready in time")


def run_agent(offline: bool, bug: str | None = None, run_dir: str | None = None, view: bool = False) -> dict:
    load_dotenv(_ROOT / ".env")
    from .observability import setup as observability_setup

    if observability_setup():
        print("agent-run: LangWatch tracing enabled")
    config = AgentConfig.from_env()
    budget = CostGuard.from_env()
    llm = None if offline else LLMClient(config, budget)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "-offline" if offline else (f"-{bug}" if bug else "")
    run_dir = run_dir or str(_ROOT / "agent_runs" / f"{stamp}{suffix}")
    deps = AgentDeps(
        config=config, budget=budget, llm=llm, offline=offline,
        generated_spec_path=str(_ROOT / "generated_specs" / "payflow_spec.py"),
        generated_mr_path=str(_ROOT / "generated_specs" / "payflow_mr.py"),
    )

    checkpointer = MemorySaver()
    app = build_graph(deps, checkpointer=checkpointer)
    thread = {"configurable": {"thread_id": "run"}, "recursion_limit": 60}

    print(f"agent-run: model={config.model} offline={offline} bug={bug or 'none'}")
    print(f"agent-run: artifacts -> {run_dir}")

    import tempfile

    with tempfile.TemporaryDirectory(prefix="payflow_agent_") as tmp:
        db = str(Path(tmp) / "payflow.db")
        with live_payflow(db, bug=bug, capture_fee=config.capture_fee) as server:
            initial = {
                "sut_base_url": server.base_url,
                "run_dir": run_dir,
                "iteration": 0,
                "max_iterations": config.max_iterations,
                "history": [],
            }
            try:
                if view:
                    _invoke_with_view(app, initial, thread, deps, run_dir)
                else:
                    app.invoke(initial, thread)
            except BudgetExceeded as exc:
                snapshot = dict(app.get_state(thread).values)
                snapshot["aborted"] = True
                snapshot["abort_reason"] = str(exc)
                write_report(snapshot, deps, run_dir)
                print(f"agent-run: ABORTED on budget: {exc}")

    summary = Path(run_dir) / "summary.txt"
    if summary.exists() and not view:
        print("\n" + summary.read_text(encoding="utf-8"))
    return {"run_dir": run_dir}


def _invoke_with_view(app, initial: dict, thread: dict, deps, run_dir: str) -> None:
    """Stream the graph and drive the live Rich view (agent-run --view).

    Uses LangGraph's update stream, one chunk per node completion, so the view
    needs no hooks inside the graph or the nodes. On completion it renders the
    committed report so the final frame is exactly what explain-run would show.
    """
    import json

    from tools.run_view import LiveRunView, render_report

    with LiveRunView() as live:
        # The execute node streams per property outcomes to this sink while it
        # blocks on the pytest subprocess, so the slow step shows live progress.
        deps.on_progress = live.on_progress
        for chunk in app.stream(initial, thread, stream_mode="updates"):
            for node_name, state_update in chunk.items():
                if isinstance(state_update, dict):
                    live.on_node(node_name, state_update)
    report_path = Path(run_dir) / "report.json"
    if report_path.exists():
        render_report(json.loads(report_path.read_text(encoding="utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser(description="PayFlow property generation agent")
    parser.add_argument("--offline", action="store_true", help="no LLM calls; use golden proposals")
    parser.add_argument("--bug", choices=["fm_a", "fm_b", "fm_c"], default=None)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--view", action="store_true", help="live TUI of the pipeline as it runs")
    args = parser.parse_args()
    run_agent(offline=args.offline, bug=args.bug, run_dir=args.run_dir, view=args.view)
    return 0


if __name__ == "__main__":
    sys.exit(main())
