"""Unit tests for the explorer's classification + graceful skip (ADR-0007).

Free and deterministic: the replay subprocess is monkeypatched, so no key, no tokens,
and no real pytest run happen here.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from mutation.semantic import explorer


def test_failing_nodes_parses_rA_summary() -> None:
    stdout = (
        "some noise\n"
        "FAILED mutation/replay/test_agent_replay.py::TestGeneratedMachine::runTest - AssertionError\n"
        "FAILED mutation/replay/test_agent_replay.py::test_mr_3 - Falsifying example\n"
        "1 passed\n"
    )
    assert explorer._failing_nodes(stdout) == [
        "mutation/replay/test_agent_replay.py::TestGeneratedMachine::runTest",
        "mutation/replay/test_agent_replay.py::test_mr_3",
    ]


def test_run_replay_survived(monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    assert explorer._run_replay(30) == ("survived", [])


def test_run_replay_killed_with_attribution(monkeypatch) -> None:
    out = "FAILED path::test_x - boom\n"
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout=out, stderr=""))
    status, nodes = explorer._run_replay(30)
    assert status == "killed" and nodes == ["path::test_x"]


def test_run_replay_timeout(monkeypatch) -> None:
    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=30)
    monkeypatch.setattr(subprocess, "run", _raise)
    assert explorer._run_replay(30) == ("timeout", [])


def test_run_replay_broken_import_is_error_not_kill(monkeypatch) -> None:
    # exit 5 (no tests collected) must not be flattered into a kill.
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=5, stdout="", stderr=""))
    assert explorer._run_replay(30) == ("error", [])


def test_generate_skips_without_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    gen = explorer._generate("claude-sonnet-5", explorer._budget())
    assert gen.source.startswith("skipped") and gen.mutants == []


def test_main_skips_cleanly_and_writes_report(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = tmp_path / "semantic_report.json"
    monkeypatch.setattr(explorer, "_REPORT", report)
    monkeypatch.setattr(explorer.sys, "argv", ["semantic-mutation"])

    assert explorer.main() == 0  # zero authority: never fails

    data = json.loads(report.read_text())
    assert data["source"].startswith("skipped")
    assert data["summary"] == {"total": 0, "killed": 0, "survived": 0,
                               "timeout": 0, "other": 0}
    assert data["mutants"] == []


def test_budget_env_override(monkeypatch) -> None:
    monkeypatch.setenv("PAYFLOW_SEMANTIC_MAX_CALLS", "7")
    monkeypatch.setenv("PAYFLOW_SEMANTIC_MAX_TOKENS", "123")
    b = explorer._budget()
    assert b.max_calls == 7 and b.max_tokens == 123
