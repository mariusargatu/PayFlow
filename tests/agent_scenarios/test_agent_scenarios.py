"""Layer 2 rigged world scenarios: does triage classify a known wrong world right?

Two scenarios from design section 9, run against a live PayFlow served in process:

  (a) broken capture check  -> the INV-1 over capture guard is dropped, so an
      over capture is accepted. Triage must call the resulting failure real_bug.
  (b) overly strict invariant -> a CORRECT build is asked to satisfy
      captured == authorized, which a legal partial capture falsifies. Triage must
      call it bad_invariant, not real_bug: the assumption is wrong, not the system.

On the langwatch-scenario library: deferred. Its API is built around multi turn
chat (an AgentAdapter over messages, a UserSimulatorAgent, a JudgeAgent), while
triage is a single shot structured classifier with no user to simulate and no
dialogue; adapting it would discard triage's structured output discipline and pull
79 transitive packages into a repo whose thesis is legibility. Because triage
already returns a structured verdict, the "judge" collapses to a deterministic
assertion on that verdict, no separate LLM judge call is needed. See
ADR-0002 for the local LangWatch and langwatch-scenario decision.

Real triage calls (gpt-5.4-nano), key gated. Marker: layer2.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from _layer2 import KEY_SKIP_REASON
from _rigged import broken_capture_patch, served_sut

pytestmark = [
    pytest.mark.layer2,
    pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason=KEY_SKIP_REASON),
]

_ROOT = Path(__file__).resolve().parents[2]
_HERE = Path(__file__).resolve().parent
_OVER_CAPTURE_PROBE = _HERE / "_over_capture_probe.py"
_OVERSTRICT_SPEC = _HERE / "_overly_strict_invariant_spec.py"


def _proposed_context():
    """Rules and invariants from the latest committed agent run (as triage saw them)."""
    from agent.schemas import Invariant, Rule
    from tools.triage_validation import _latest_run_report

    report = _latest_run_report() or {}
    rules = [Rule(**r) for r in report.get("proposed_rules", [])]
    invariants = [Invariant(**i) for i in report.get("proposed_invariants", [])]
    return rules, invariants


def _run_execute(runner, base_url: str, spec_path: Path, max_examples: str = "50"):
    from agent.nodes.execute import execute

    os.environ["PAYFLOW_SPEC_MAX_EXAMPLES"] = max_examples
    state = {"sut_base_url": base_url, "generated_spec_path": str(spec_path)}
    state.update(execute(state, runner.deps))
    return state


def test_scenario_broken_capture_is_real_bug(triage_runner):
    rules, invariants = _proposed_context()
    with broken_capture_patch():
        with tempfile.TemporaryDirectory(prefix="payflow_scn_a_") as tmp:
            with served_sut(str(Path(tmp) / "sut.db"), triage_runner.config.capture_fee) as url:
                state = _run_execute(triage_runner, url, _OVER_CAPTURE_PROBE)

    result = state["hypothesis_results"]
    assert not result.passed, "scenario (a): the broken build produced no failure to triage"

    state["proposed_rules"] = rules
    state["proposed_invariants"] = invariants
    verdicts = triage_runner.verdicts(state)
    assert verdicts, "scenario (a): triage returned no verdict"
    for ref, classification in verdicts.items():
        assert classification == "real_bug", (
            f"scenario (a): triage should call the accepted over-capture a real_bug, "
            f"got {ref} -> {classification}"
        )


def test_scenario_overly_strict_invariant_is_bad_invariant(triage_runner):
    from agent.schemas import Invariant

    rules, invariants = _proposed_context()
    # The overly strict invariant the scenario adds to the proposal set.
    invariants = [
        *invariants,
        Invariant(
            id="INV-9",
            name="captured_equals_authorized",
            kind="captured_le_authorized",
            description="Every captured intent has captured_amount == authorized_amount "
            "(assumes captures are always for the full authorized amount).",
            rationale="Assumes no partial captures ever occur.",
        ),
    ]

    with tempfile.TemporaryDirectory(prefix="payflow_scn_b_") as tmp:
        with served_sut(str(Path(tmp) / "sut.db"), triage_runner.config.capture_fee) as url:
            state = _run_execute(triage_runner, url, _OVERSTRICT_SPEC)

    result = state["hypothesis_results"]
    assert not result.passed, (
        "scenario (b): the correct build satisfied the overly strict invariant, "
        "so there is nothing to triage"
    )

    state["proposed_rules"] = rules
    state["proposed_invariants"] = invariants
    verdicts = triage_runner.verdicts(state)
    assert verdicts, "scenario (b): triage returned no verdict"
    for ref, classification in verdicts.items():
        assert classification == "bad_invariant", (
            f"scenario (b): triage should call the overly strict invariant a "
            f"bad_invariant, got {ref} -> {classification}"
        )
