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

import contextlib
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


def trace_run(name: str):
    """Open a run level LangWatch trace so node spans nest inside it.

    The per node ``trace_node`` spans and the ``score_run`` evaluation both need a
    current trace; without one the SDK warns and nothing associates. The runner
    wraps the whole graph execution in this. A clean ``nullcontext`` when tracing
    is off, and a nullcontext on any SDK error, so the run is never affected.
    """
    if not setup():
        return contextlib.nullcontext()
    try:
        import langwatch

        return langwatch.trace(name=name)
    except Exception:
        return contextlib.nullcontext()


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

                from .roles import LABEL, role_of

                role = role_of(name)
                with langwatch.span(
                    name=f"{name} [{role}]",
                    type="chain",
                    attributes={"payflow.role": role, "payflow.role_label": LABEL[role]},
                ) as span:
                    result = fn(state, deps)
                    try:
                        span.update(output=_summarize_node(result))
                    except Exception:
                        pass
                    return result
            except Exception:
                return fn(state, deps)

        return wrapper

    return decorate


def _summarize_node(result: Any) -> str:
    """A compact, human readable summary of what a node produced, for the span
    output so a trace reads as a story (names, not full objects)."""
    if not isinstance(result, dict):
        return str(result)[:500]
    lines: list[str] = []

    def names(items, attr):
        out = []
        for it in items or []:
            out.append(getattr(it, attr, None) or (it.get(attr) if isinstance(it, dict) else str(it)))
        return out

    if result.get("endpoints"):
        lines.append("endpoints: " + ", ".join(names(result["endpoints"], "operation_id")))
    if result.get("proposed_rules"):
        lines.append("rules: " + ", ".join(names(result["proposed_rules"], "name")))
    if result.get("proposed_invariants"):
        lines.append("invariants: " + ", ".join(names(result["proposed_invariants"], "name")))
    if result.get("proposed_relations"):
        lines.append("relations: " + ", ".join(names(result["proposed_relations"], "name")))
    if result.get("triaged_failures"):
        verdicts = [
            f"{getattr(v, 'failure_ref', '?')}={getattr(v, 'classification', '?')}"
            for v in result["triaged_failures"]
        ]
        lines.append("verdicts: " + ", ".join(verdicts))
    if result.get("history"):
        lines.append("note: " + " | ".join(str(h) for h in result["history"]))
    return "\n".join(lines)[:1500] or "(no proposals this step)"


class _NoopSpan:
    def update(self, **_kw: Any) -> None:
        pass


@contextlib.contextmanager
def llm_span(name: str, model: str, system: str, user: str):
    """Wrap one structured LLM proposal in a LangWatch ``llm`` span so the trace
    shows the real prompt and the model's answer. Guarded: a no op span when
    tracing is off or the SDK errors, so ``llm.py`` is unaffected either way."""
    if not setup():
        yield _NoopSpan()
        return
    try:
        import langwatch

        prompt = f"[system]\n{system}\n\n[user]\n{user}"
        with langwatch.span(name=name, type="llm", model=model, input=prompt) as span:
            yield span
    except Exception:
        yield _NoopSpan()


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
        try:
            trace.update(
                metadata={
                    "model": cost.get("model", ""),
                    "proposed_total": funnel.get("proposed_total", 0),
                    "survived_falsification": survived,
                    "flagged_real_bug": funnel.get("flagged_real_bug", []),
                    "iterations_used": funnel.get("iterations_used", 0),
                    "approx_cost_usd": cost.get("approx_cost_usd", 0.0),
                }
            )
        except Exception:
            pass
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
