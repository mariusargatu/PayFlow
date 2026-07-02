"""`uv run python tools/judge_comparison.py`: pick the triage judge empirically.

For each candidate model the tool runs the Layer 2 fixture bank (the same
tests/agent_metamorphic fixtures and no information transforms, exercised
programmatically rather than through pytest):

  - twice with voting OFF, to measure the RAW judge's accuracy and its stability
    across independent runs and a paraphrase (a no information transform), and
  - once with voting ON (PAYFLOW_TRIAGE_VOTES calls, majority), to measure the
    SHIPPED configuration.

The void regression fixture (agent_runs/20260702T043505Z, carrying the new
accepted slice annotation) rides along; its verdict should be bad_rule.

Output: a comparison table (JSON + text) under agent_runs/<ts>-judge-comparison/,
per model accuracy, stability, cost per verdict, and the void verdict, plus a
per dollar ranking. Judge selection is by measured accuracy and stability per
dollar, never by size or recency (ADR-0004).

Costs OpenAI tokens. A total spend cap (default $3) guards the whole comparison;
measured spend is printed and written to the artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
# The Layer 2 fixture bank lives under tests/; reuse it rather than duplicate.
sys.path.insert(0, str(_ROOT / "tests" / "agent_metamorphic"))
sys.path.insert(0, str(_ROOT))

from agent.budget import CostGuard  # noqa: E402
from agent.config import AgentConfig  # noqa: E402
from agent.graph import AgentDeps  # noqa: E402
from agent.llm import LLMClient  # noqa: E402
from agent.nodes.triage import triage  # noqa: E402

CANDIDATES = ["gpt-5-nano", "gpt-5.4-nano", "gpt-5.4-mini", "gpt-5.4"]
DEFAULT_BUDGET_USD = 3.0
VOTES_ON = 3


def _fixtures():
    from fixtures import ALL_FIXTURES, VOID_ILLEGAL_STATE

    return list(ALL_FIXTURES) + [VOID_ILLEGAL_STATE]


def _verdict(state: dict, deps: AgentDeps) -> str:
    """Run the real triage node on one single failure state, return its verdict."""
    out = triage(state, deps)
    ref = state["hypothesis_results"].failures[0].tag()
    for v in out["triaged_failures"]:
        if v.failure_ref == ref:
            return v.classification
    return "<missing>"


@dataclass
class ModelResult:
    model: str
    accuracy_raw: float
    accuracy_voted: float
    stability: float
    cost_usd: float
    verdicts_produced: int
    cost_per_verdict: float
    void_verdict_raw: str
    void_verdict_voted: str
    per_fixture: dict = field(default_factory=dict)
    note: str = ""


def _run_model(model: str) -> ModelResult:
    from transforms import single_failure_state

    # Two budgets: OFF passes (raw judge: two reruns + two paraphrases) and the ON
    # pass (the shipped voted config). Keeping them apart lets $/verdict report the
    # true shipped cost of one triage verdict, not an average diluted by the reruns.
    budget_off = CostGuard(max_calls=10_000, max_tokens=50_000_000)
    budget_on = CostGuard(max_calls=10_000, max_tokens=50_000_000)
    config_off = AgentConfig(model=model, triage_votes=1)
    config_on = AgentConfig(model=model, triage_votes=VOTES_ON)
    deps_off = AgentDeps(
        config=config_off, budget=budget_off, llm=LLMClient(config_off, budget_off), offline=False
    )
    deps_on = AgentDeps(
        config=config_on, budget=budget_on, llm=LLMClient(config_on, budget_on), offline=False
    )

    pairs = [(fx, ff) for fx in _fixtures() for ff in fx.failures]
    per_fixture: dict = {}
    correct_raw = correct_voted = stable = 0
    void_raw = void_voted = "<none>"

    for fx, ff in pairs:
        run1 = _verdict(single_failure_state(fx, ff), deps_off)
        run2 = _verdict(single_failure_state(fx, ff), deps_off)
        para0 = _verdict(single_failure_state(fx, ff, paraphrase=0), deps_off)
        para1 = _verdict(single_failure_state(fx, ff, paraphrase=1), deps_off)
        voted = _verdict(single_failure_state(fx, ff), deps_on)

        # Stable = the raw judge returns one verdict under two reruns and both no
        # information paraphrases (the transforms the Layer 2 suite uses).
        is_stable = run1 == run2 == para0 == para1
        per_fixture[ff.ref] = {
            "expected": ff.expected,
            "raw_run1": run1,
            "raw_run2": run2,
            "raw_paraphrase0": para0,
            "raw_paraphrase1": para1,
            "voted": voted,
            "stable": is_stable,
            "correct_raw": run1 == ff.expected,
            "correct_voted": voted == ff.expected,
        }
        correct_raw += run1 == ff.expected
        correct_voted += voted == ff.expected
        stable += is_stable
        if ff.proposal_id == "void_illegal_state":
            void_raw, void_voted = run1, voted

    n = len(pairs)
    cost_on = budget_on.approx_cost_usd(model)
    cost = budget_off.approx_cost_usd(model) + cost_on
    return ModelResult(
        model=model,
        accuracy_raw=round(correct_raw / n, 3),
        accuracy_voted=round(correct_voted / n, 3),
        stability=round(stable / n, 3),
        cost_usd=round(cost, 6),
        verdicts_produced=n,  # shipped (voted) verdicts produced
        cost_per_verdict=round(cost_on / n, 6) if n else 0.0,
        void_verdict_raw=void_raw,
        void_verdict_voted=void_voted,
        per_fixture=per_fixture,
    )


def _rank(results: list[ModelResult]) -> list[dict]:
    """Rank by (accuracy_voted + stability) per dollar; ties prefer cheaper.

    A model that costs nothing to distinguish (cost 0) cannot happen here since
    every verdict is a paid call; guard anyway.
    """
    ranked = []
    for r in results:
        quality = (r.accuracy_voted + r.stability) / 2
        per_dollar = quality / r.cost_per_verdict if r.cost_per_verdict else 0.0
        ranked.append(
            {
                "model": r.model,
                "quality": round(quality, 3),
                "accuracy_voted": r.accuracy_voted,
                "stability": r.stability,
                "cost_per_verdict": r.cost_per_verdict,
                "quality_per_dollar": round(per_dollar, 1),
            }
        )
    # Highest quality per dollar first; break ties by cheaper cost_per_verdict.
    ranked.sort(key=lambda x: (-x["quality_per_dollar"], x["cost_per_verdict"]))
    return ranked


def _text_table(results: list[ModelResult], ranked: list[dict], spend: float) -> str:
    lines = [
        "PayFlow judge comparison: Layer 2 fixture bank (accuracy + stability)",
        f"fixtures per model: {len(_fixtures())} (5 Layer 2 + 1 void regression); "
        f"voting ON = best of {VOTES_ON}",
        "",
        f"{'model':14} {'acc_raw':>8} {'acc_vote':>9} {'stability':>10} "
        f"{'$/verdict':>11} {'void_raw':>12} {'void_vote':>12}",
    ]
    for r in results:
        lines.append(
            f"{r.model:14} {r.accuracy_raw:>8} {r.accuracy_voted:>9} {r.stability:>10} "
            f"{r.cost_per_verdict:>11} {r.void_verdict_raw:>12} {r.void_verdict_voted:>12}"
        )
    lines += ["", "ranking (quality per dollar; quality = (acc_vote + stability) / 2):"]
    for i, row in enumerate(ranked, 1):
        lines.append(
            f"  {i}. {row['model']:14} quality={row['quality']} "
            f"per_dollar={row['quality_per_dollar']} $/verdict={row['cost_per_verdict']}"
        )
    lines += ["", f"total measured spend: ${round(spend, 4)}"]
    return "\n".join(lines) + "\n"


def _dump_accepted(report_path: str) -> int:
    """Regenerate generated_specs/accepted_proposals.json from a run report."""
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    out = {
        "_note": (
            "Deterministic triage evidence: the accepted, committed Layer 1 slice. "
            "Extracted from the source_run report. MUST be regenerated whenever the "
            "committed generated_specs/ slice changes under the same acceptance "
            "decision, via tools/judge_comparison.py --dump-accepted <report.json> (or "
            "by hand). agent.annotations diffs failing proposals against this file to "
            "annotate triage; it is evidence, never a verdict."
        ),
        "source_run": str(Path(report_path).parent),
        "model": report.get("model"),
        "rules": [
            {
                "operation_id": r["operation_id"],
                "name": r["name"],
                "effect": r["effect"],
                "legal_states": r.get("legal_states", []),
                "success_status": r.get("success_status"),
                "amount_field": r.get("amount_field"),
            }
            for r in report.get("proposed_rules", [])
        ],
        "invariants": [
            {"id": i["id"], "name": i["name"], "kind": i["kind"]}
            for i in report.get("proposed_invariants", [])
        ],
        "relations": [
            {
                "id": r["id"],
                "name": r["name"],
                "transform": r["transform"],
                "fee_handling": r["fee_handling"],
            }
            for r in report.get("proposed_relations", [])
        ],
    }
    dest = _ROOT / "generated_specs" / "accepted_proposals.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {dest}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Empirical triage judge comparison")
    parser.add_argument(
        "--dump-accepted",
        metavar="REPORT_JSON",
        help="regenerate generated_specs/accepted_proposals.json from a run report, then exit",
    )
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--models", nargs="*", default=CANDIDATES)
    args = parser.parse_args()

    if args.dump_accepted:
        return _dump_accepted(args.dump_accepted)

    from dotenv import load_dotenv

    load_dotenv(_ROOT / ".env")
    import os

    if not os.environ.get("OPENAI_API_KEY"):
        print("judge_comparison: OPENAI_API_KEY not set; nothing to measure")
        return 1

    results: list[ModelResult] = []
    spend = 0.0
    for model in args.models:
        if spend >= args.budget:
            print(f"budget cap ${args.budget} reached; skipping {model}")
            break
        print(f"judge_comparison: measuring {model} ...")
        result = _run_model(model)
        spend += result.cost_usd
        results.append(result)
        print(
            f"  acc_raw={result.accuracy_raw} acc_vote={result.accuracy_voted} "
            f"stability={result.stability} $/verdict={result.cost_per_verdict} "
            f"void raw={result.void_verdict_raw} voted={result.void_verdict_voted} "
            f"(cumulative ${round(spend, 4)})"
        )

    ranked = _rank(results)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _ROOT / "agent_runs" / f"{stamp}-judge-comparison"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": stamp,
        "votes_on": VOTES_ON,
        "fixtures": [ff.ref for fx in _fixtures() for ff in fx.failures],
        "budget_usd": args.budget,
        "total_spend_usd": round(spend, 6),
        "results": [r.__dict__ for r in results],
        "ranking": ranked,
    }
    (out_dir / "comparison.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    table = _text_table(results, ranked, spend)
    (out_dir / "comparison.txt").write_text(table, encoding="utf-8")
    print("\n" + table)
    print(f"artifacts -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
