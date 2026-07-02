"""Per run cost guard (ADR-0002 consequence, mandatory).

A runaway refine loop must never spend unbounded money. This object caps both
the total number of LLM calls and the total tokens (read from response usage
metadata); crossing either raises ``BudgetExceeded``, which the runner turns
into a clean partial report rather than a crash. Caps are env overridable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_MAX_CALLS = 40
DEFAULT_MAX_TOKENS = 200_000

# Best effort per million token USD rates for the approximate cost line in the
# report. Marked approximate on purpose: the token counts are exact (from usage
# metadata), the dollar conversion is an estimate at these assumed rates.
# Latest generation only (the 4.x family costs more per unit of judgment and is
# never selected). Rates checked 2026-07-02 against the public pricing pages.
_PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-5.4": (2.50, 15.00),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5-nano": (0.05, 0.40),  # incumbent judge, kept for comparison runs
}


class BudgetExceeded(Exception):
    """Raised before a call that would cross a cap, or after usage crosses one."""


@dataclass
class CostGuard:
    max_calls: int = DEFAULT_MAX_CALLS
    max_tokens: int = DEFAULT_MAX_TOKENS
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    _events: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "CostGuard":
        return cls(
            max_calls=int(os.environ.get("PAYFLOW_AGENT_MAX_CALLS", DEFAULT_MAX_CALLS)),
            max_tokens=int(os.environ.get("PAYFLOW_AGENT_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
        )

    def before_call(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(
                f"LLM call cap reached ({self.calls}/{self.max_calls} calls); "
                "aborting with a partial report"
            )
        if self.total_tokens >= self.max_tokens:
            raise BudgetExceeded(
                f"token cap reached ({self.total_tokens}/{self.max_tokens} tokens); "
                "aborting with a partial report"
            )

    def record(self, usage: dict | None) -> None:
        usage = usage or {}
        self.calls += 1
        self.input_tokens += int(usage.get("input_tokens", 0) or 0)
        self.output_tokens += int(usage.get("output_tokens", 0) or 0)
        self.total_tokens += int(usage.get("total_tokens", 0) or 0)

    def approx_cost_usd(self, model: str) -> float:
        rate = _PRICES_PER_MTOK.get(model)
        if rate is None:
            return 0.0
        in_rate, out_rate = rate
        return round(
            self.input_tokens / 1_000_000 * in_rate
            + self.output_tokens / 1_000_000 * out_rate,
            6,
        )

    def summary(self, model: str) -> dict:
        return {
            "model": model,
            "calls": self.calls,
            "max_calls": self.max_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "approx_cost_usd": self.approx_cost_usd(model),
            "approx_cost_note": "token counts exact; USD at assumed public nano rates",
        }
