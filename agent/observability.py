"""Guarded LangWatch tracing for the property generation agent (design §9).

ADR-0002 puts LangWatch local, reached through ``LANGWATCH_ENDPOINT``. Every hook
here is a clean no op unless LangWatch is BOTH installed AND pointed at an
endpoint: missing either means zero crashes and zero slowdown, so the agent runs
identically with or without observability. Every LangWatch call is wrapped so a
future SDK API change degrades to a no op rather than breaking a paid agent run.

Status: the nodes are instrumented; the local docker compose that would give
``LANGWATCH_ENDPOINT`` a home is deferred (ADR-0002).
Until an endpoint exists this stays dark by design, which is the whole point of
the guard.
"""

from __future__ import annotations

import functools
import os
from typing import Any, Callable

_setup_done: bool | None = None


def _enabled() -> bool:
    return bool(os.environ.get("LANGWATCH_ENDPOINT"))


def setup() -> bool:
    """Idempotent LangWatch init. Returns True only if tracing is live."""
    global _setup_done
    if _setup_done is not None:
        return _setup_done
    if not _enabled():
        _setup_done = False
        return False
    try:
        import langwatch

        langwatch.setup(
            endpoint_url=os.environ["LANGWATCH_ENDPOINT"],
            api_key=os.environ.get("LANGWATCH_API_KEY", "local-dev"),
        )
        _setup_done = True
    except Exception:
        _setup_done = False
    return _setup_done


def trace_node(name: str) -> Callable[[Callable], Callable]:
    """Wrap a graph node (state, deps) -> dict in a LangWatch span.

    A no op wrapper when tracing is off, so it is always safe to apply in
    ``graph.py`` regardless of environment. Node semantics and the compiled graph
    shape (and therefore the drift gate) are unaffected: only the callable is
    wrapped, never the node registration.
    """

    def decorate(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: Any, deps: Any) -> Any:
            if not setup():
                return fn(state, deps)
            try:
                import langwatch

                with langwatch.span(name=name, type="chain"):
                    return fn(state, deps)
            except Exception:
                return fn(state, deps)

        return wrapper

    return decorate


def score_run(funnel: dict, cost: dict) -> None:
    """Push per run invariant/relation survival scores (design §9 scoring).

    Records the discovery funnel as evaluations: how many proposals survived
    falsification, how many were flagged as real bugs, and the token cost. No op
    unless tracing is live.
    """
    if not setup():
        return
    try:
        import langwatch

        trace = langwatch.get_current_trace()
        if trace is None:
            return
        proposed = max(funnel.get("proposed_total", 0), 1)
        survived = funnel.get("survived_falsification", 0)
        trace.add_evaluation(
            name="proposals_survived_falsification",
            passed=funnel.get("final_failing_count", 0) == 0,
            score=survived / proposed,
            details=(
                f"{survived}/{proposed} proposals survived; "
                f"{len(funnel.get('flagged_real_bug', []))} flagged real bug; "
                f"{cost.get('total_tokens', 0)} tokens"
            ),
        )
    except Exception:
        return
