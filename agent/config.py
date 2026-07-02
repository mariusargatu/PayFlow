"""Agent run configuration.

The default model is ``gpt-5.4-nano``, selected empirically per ADR-0004: it won
the judge comparison on the Layer 2 fixture bank (best verdict accuracy and
stability per dollar), beating both the larger ``gpt-5.4`` (same quality, far
higher cost) and ``gpt-5.4-mini`` (worst of the candidates). Judges are chosen by
measurement, never by size or recency. Overridable via ``PAYFLOW_AGENT_MODEL``;
rerun ``tools/judge_comparison.py`` to reselect.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "gpt-5.4-nano"
MAX_ITERATIONS = 5  # refine passes before flagging for a human (ADR-0006, was 3)
# Triage runs best of N independent calls (majority vote; a tie or three way split
# escalates to needs_human). 1 restores the old single call behavior. Voting is a
# mitigation for the measured judge nondeterminism (the flaky judge journey entry);
# ADR-0004 records why the shipped default is 3.
DEFAULT_TRIAGE_VOTES = 3
# Hypothesis example execution costs wall clock time, not tokens (only the LLM
# nodes spend tokens), so this budget stays modest for run time while being high
# enough to reach the deep states where boundary and solvency violations surface.
DEFAULT_MAX_EXAMPLES = 50
DEFAULT_STEP_COUNT = 18
DEFAULT_CAPTURE_FEE = 30
# Metamorphic relations run two full scenarios per example over HTTP, so they are
# heavier than a single stateful step; a modest budget keeps the committed replay
# slice honest (design section 8) and per example cost bounded. Env overridable.
DEFAULT_MR_MAX_EXAMPLES = 20


@dataclass(frozen=True)
class AgentConfig:
    model: str = DEFAULT_MODEL
    max_iterations: int = MAX_ITERATIONS
    max_examples: int = DEFAULT_MAX_EXAMPLES
    stateful_step_count: int = DEFAULT_STEP_COUNT
    capture_fee: int = DEFAULT_CAPTURE_FEE
    mr_max_examples: int = DEFAULT_MR_MAX_EXAMPLES
    triage_votes: int = DEFAULT_TRIAGE_VOTES

    @classmethod
    def from_env(cls) -> "AgentConfig":
        return cls(
            model=os.environ.get("PAYFLOW_AGENT_MODEL", DEFAULT_MODEL),
            max_examples=int(
                os.environ.get("PAYFLOW_AGENT_MAX_EXAMPLES", DEFAULT_MAX_EXAMPLES)
            ),
            capture_fee=int(os.environ.get("PAYFLOW_CAPTURE_FEE", DEFAULT_CAPTURE_FEE)),
            mr_max_examples=int(
                os.environ.get("PAYFLOW_MR_MAX_EXAMPLES", DEFAULT_MR_MAX_EXAMPLES)
            ),
            triage_votes=int(
                os.environ.get("PAYFLOW_TRIAGE_VOTES", DEFAULT_TRIAGE_VOTES)
            ),
        )
