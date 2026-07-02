"""Thin wrapper over langchain-openai for structured proposals.

Every LLM node calls ``propose`` with a pydantic schema; the model may only
answer in that shape. Usage metadata from the raw response feeds the cost guard
so the token cap is enforced from real numbers, not estimates. The API key is
read from the environment by ``ChatOpenAI`` and is never logged or printed here.
"""

from __future__ import annotations

from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from .budget import CostGuard
from .config import AgentConfig

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self, config: AgentConfig, budget: CostGuard) -> None:
        self._config = config
        self._budget = budget
        # No temperature: gpt-5 reasoning models reject it, and structured
        # output already constrains the shape.
        self._llm = ChatOpenAI(model=config.model)

    def propose(self, schema: type[T], system: str, user: str) -> T:
        self._budget.before_call()
        structured = self._llm.with_structured_output(schema, include_raw=True)
        result = structured.invoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
        raw = result.get("raw")
        usage = getattr(raw, "usage_metadata", None)
        self._budget.record(usage)
        parsed = result.get("parsed")
        if parsed is None:
            error = result.get("parsing_error")
            raise RuntimeError(f"model returned no parsable structured output: {error}")
        return parsed
