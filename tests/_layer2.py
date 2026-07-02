"""Shared helpers for the Layer 2 suites (agent_metamorphic + agent_scenarios).

Layer 2 tests make real triage LLM calls (gpt-5.4-nano, cheap) and are gated on
OPENAI_API_KEY: absent, they skip with an honest message rather than fail. The
key is read from .env for local runs and from CI secrets in the nightly lane.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

KEY_SKIP_REASON = (
    "Layer 2 needs OPENAI_API_KEY for real triage LLM calls; "
    "set it in .env locally or in CI secrets"
)


def load_env_key() -> bool:
    """Load .env (best effort) and report whether an OpenAI key is present."""
    try:
        from dotenv import load_dotenv

        load_dotenv(_ROOT / ".env")
    except ImportError:
        pass
    return bool(os.environ.get("OPENAI_API_KEY"))


def _state_key(state: dict) -> tuple:
    """A deterministic cache key over everything that shapes the triage prompt."""
    result = state["hypothesis_results"]
    failures = tuple(
        (f.kind, f.proposal_id, f.message, f.counterexample) for f in result.failures
    )
    rules = tuple(
        (r.name, r.effect, tuple(r.legal_states)) for r in state.get("proposed_rules", [])
    )
    invariants = tuple((i.id, i.kind) for i in state.get("proposed_invariants", []))
    relations = tuple(
        (r.id, r.transform, r.fee_handling) for r in state.get("proposed_relations", []) or []
    )
    return (failures, rules, invariants, relations, os.environ.get("PAYFLOW_TRIAGE_REGRESSION"))


class CachingTriageRunner:
    """Runs the real triage node, caching verdicts per distinct triage input.

    Caching within a session keeps the AGENT-MR suite under its LLM call budget:
    the single failure baseline for a fixture is computed once and reused by the
    paraphrase, padding, and ground truth checks that all start from it.
    """

    def __init__(self) -> None:
        import dataclasses

        from agent.budget import CostGuard
        from agent.config import AgentConfig
        from agent.graph import AgentDeps
        from agent.llm import LLMClient

        # Layer 2 measures the RAW judge (one triage call), so its stability
        # findings describe the model itself, not the voted mitigation. Majority
        # voting is measured separately by tools/judge_comparison.py. Enrichment
        # (accepted slice annotations) stays on: it is part of the shipped triage
        # node, and is deterministic and stable under the no information transforms.
        self.config = dataclasses.replace(AgentConfig.from_env(), triage_votes=1)
        self.budget = CostGuard.from_env()
        self.deps = AgentDeps(
            config=self.config,
            budget=self.budget,
            llm=LLMClient(self.config, self.budget),
            offline=False,
        )
        self._cache: dict[tuple, dict[str, str]] = {}

    def verdicts(self, state: dict) -> dict[str, str]:
        """Map each failure_ref to its triage classification (cached)."""
        key = _state_key(state)
        if key not in self._cache:
            from agent.nodes.triage import triage

            out = triage(state, self.deps)
            self._cache[key] = {
                v.failure_ref: v.classification for v in out["triaged_failures"]
            }
        return self._cache[key]

    def cost_line(self) -> str:
        return "LAYER2-COST " + json.dumps(self.budget.summary(self.config.model))
