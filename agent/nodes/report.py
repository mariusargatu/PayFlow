"""report node: write JSON + human summary artifacts (no LLM).

``write_report`` is reused by the runner's abort path so a budget exceeded run
still leaves a partial report behind rather than crashing empty.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from ..schemas import TestRunResult
from ..state import AgentState


def _base_proposal(proposal_id: str) -> str:
    for suffix in ("_over_limit", "_illegal_state"):
        if proposal_id.endswith(suffix):
            return proposal_id[: -len(suffix)]
    return proposal_id


def _effective_rules(state: AgentState):
    """The rules actually compiled: last proposal per name (refinements win)."""
    seen = {}
    for rule in state.get("proposed_rules", []):
        seen[rule.name] = rule
    return list(seen.values())


def _funnel(state: AgentState) -> dict:
    rules = _effective_rules(state)
    invariants = state.get("proposed_invariants", [])
    relations = state.get("proposed_relations", []) or []
    result: TestRunResult | None = state.get("hypothesis_results")
    failed = sorted({f.tag() for f in result.failures}) if result else []
    verdicts = state.get("triaged_failures", []) or []
    real_bugs = [v.failure_ref for v in verdicts if v.classification == "real_bug"]
    needs_human = [v.failure_ref for v in verdicts if v.classification == "needs_human"]
    proposed = len(rules) + len(invariants) + len(relations)
    return {
        "proposed_rules": len(rules),
        "proposed_invariants": len(invariants),
        "proposed_relations": len(relations),
        "proposed_total": proposed,
        "final_failing_proposals": failed,
        "final_failing_count": len(failed),
        "survived_falsification": proposed - len({_base_proposal(f.split(":", 1)[-1]) for f in failed}),
        "flagged_real_bug": sorted(set(real_bugs)),
        "flagged_needs_human": sorted(set(needs_human)),
        "iterations_used": state.get("iteration", 0),
    }


def _serialise_result(result: TestRunResult | None) -> dict | None:
    if result is None:
        return None
    return {
        "passed": result.passed,
        "error": result.error,
        "failures": [dataclasses.asdict(f) for f in result.failures],
        "output_tail": result.output_tail,
    }


def build_report(state: AgentState, deps) -> dict:
    result = state.get("hypothesis_results")
    return {
        "model": deps.config.model,
        "aborted": state.get("aborted", False),
        "abort_reason": state.get("abort_reason", ""),
        "funnel": _funnel(state),
        "endpoints": [e.operation_id for e in state.get("endpoints", [])],
        "proposed_rules": [r.model_dump() for r in _effective_rules(state)],
        "proposed_invariants": [i.model_dump() for i in state.get("proposed_invariants", [])],
        "proposed_relations": [r.model_dump() for r in state.get("proposed_relations", []) or []],
        "hypothesis_results": _serialise_result(result),
        "triaged_failures": [v.model_dump() for v in state.get("triaged_failures", []) or []],
        "cost": deps.budget.summary(deps.config.model),
        "history": state.get("history", []),
    }


def _human_summary(report: dict) -> str:
    f = report["funnel"]
    cost = report["cost"]
    lines = [
        "PayFlow property generation agent, run summary",
        f"model: {report['model']}",
        f"aborted: {report['aborted']} {report['abort_reason']}".rstrip(),
        "",
        "funnel:",
        f"  proposed:   {f['proposed_total']} "
        f"({f['proposed_rules']} rules, {f['proposed_invariants']} invariants, "
        f"{f.get('proposed_relations', 0)} relations)",
        f"  survived falsification: {f['survived_falsification']}",
        f"  final failing proposals: {f['final_failing_count']} {f['final_failing_proposals']}",
        f"  flagged real bug: {f['flagged_real_bug']}",
        f"  flagged needs human (triage vote split): {f.get('flagged_needs_human', [])}",
        f"  refine iterations used: {f['iterations_used']}",
        "",
        "cost:",
        f"  llm calls: {cost['calls']}/{cost['max_calls']}",
        f"  tokens: {cost['total_tokens']}/{cost['max_tokens']} "
        f"(in {cost['input_tokens']}, out {cost['output_tokens']})",
        f"  approx usd: ${cost['approx_cost_usd']} ({cost['approx_cost_note']})",
    ]
    verdicts = report["triaged_failures"]
    if verdicts:
        lines += ["", "triage verdicts:"]
        for v in verdicts:
            lines.append(f"  {v['failure_ref']} -> {v['classification']} ({v['target']}): {v['reasoning'][:100]}")
    return "\n".join(lines) + "\n"


def write_report(state: AgentState, deps, run_dir: str) -> dict:
    report = build_report(state, deps)
    directory = Path(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (directory / "summary.txt").write_text(_human_summary(report), encoding="utf-8")
    code = state.get("generated_spec_code")
    if code:
        (directory / "generated_spec.py").write_text(code, encoding="utf-8")
    mr_code = state.get("generated_mr_code")
    if mr_code:
        (directory / "generated_mr.py").write_text(mr_code, encoding="utf-8")
    return report


def report(state: AgentState, deps) -> dict:
    run_dir = state["run_dir"]
    written = write_report(state, deps, run_dir)
    # Push the discovery funnel to LangWatch as survival scores (design §9).
    # Guarded no op unless a LangWatch endpoint is configured.
    from ..observability import score_run

    score_run(written["funnel"], written["cost"])
    return {"history": [f"report: artifacts written to {run_dir}"]}
