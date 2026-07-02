"""The property generation StateGraph (design section 7.4).

Shape:

    ingest_spec
      -> infer_endpoint_rules   (Send fan out, one branch per endpoint)
      -> infer_invariants
      -> infer_relations         (Phase 3 stub, wired but empty)
      -> compile_spec
      -> execute
      -> triage      (only on failures)  -> refine -> compile_spec  (loop, budget 5)
                                          -> report
      -> report      (on success, or once triage has nothing fixable)

Deviations from design section 7.4, stated honestly: infer_relations is a Phase 3
stub, and the "no failures, budget left -> rediscover" edge is omitted (re
running discovery with nothing falsified spends tokens for no signal). The graph
is built from whatever nodes are actually wired, so the drift gate reflects
reality.
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .budget import CostGuard
from .config import MAX_ITERATIONS, AgentConfig
from .llm import LLMClient
from .nodes.compile_spec import compile_spec
from .nodes.execute import execute
from .nodes.infer_endpoint_rules import infer_endpoint_rules
from .nodes.infer_invariants import infer_invariants
from .nodes.infer_relations import infer_relations
from .nodes.ingest_spec import ingest_spec
from .nodes.refine import refine
from .nodes.report import report
from .nodes.triage import triage
from .observability import trace_node
from .state import AgentState


@dataclass
class AgentDeps:
    config: AgentConfig
    budget: CostGuard
    llm: LLMClient | None
    offline: bool
    generated_spec_path: str = "generated_specs/payflow_spec.py"
    generated_mr_path: str = "generated_specs/payflow_mr.py"
    # None -> agent.annotations resolves the default committed slice location.
    accepted_proposals_path: str | None = None
    # Optional live progress sink: called as on_progress(kind, payload) from long
    # nodes (execute streams one call per property outcome). None in normal runs;
    # set by agent-run --view. Presentation only, never affects the run result.
    on_progress: object = None


def _structural_deps() -> AgentDeps:
    """Minimal deps for building the graph shape only (drift gate, no LLM)."""
    config = AgentConfig()
    return AgentDeps(config=config, budget=CostGuard(), llm=None, offline=True)


def _dispatch_endpoints(state: AgentState) -> list[Send]:
    return [
        Send("infer_endpoint_rules", {"current_endpoint": endpoint})
        for endpoint in state["endpoints"]
    ]


def _route_after_execute(state: AgentState) -> str:
    result = state.get("hypothesis_results")
    if result is None or result.passed:
        return "report"
    # An execution error (the compiled module could not import or run) produces a
    # synthetic failure that maps to no proposal, so triage and refine cannot act
    # on it. Route straight to report, which surfaces the error, rather than
    # spending a triage verdict on a phantom.
    if getattr(result, "error", "") == "execution_error":
        return "report"
    return "triage"


def _route_after_triage(state: AgentState) -> str:
    verdicts = state.get("triaged_failures", []) or []
    fixable = any(
        v.classification in {"bad_rule", "bad_invariant", "bad_relation"}
        for v in verdicts
    )
    if fixable and state.get("iteration", 0) < state.get("max_iterations", MAX_ITERATIONS):
        return "refine"
    return "report"


def build_graph(deps: AgentDeps | None = None, checkpointer=None):
    deps = deps or _structural_deps()

    def _n(fn):
        # LangWatch span per node (guarded no op unless an endpoint is set); the
        # wrap touches only the callable, never the graph shape or drift gate.
        traced = trace_node(fn.__name__)(fn)
        return lambda state: traced(state, deps)

    graph = StateGraph(AgentState)
    graph.add_node("ingest_spec", _n(ingest_spec))
    graph.add_node("infer_endpoint_rules", _n(infer_endpoint_rules))
    graph.add_node("infer_invariants", _n(infer_invariants))
    graph.add_node("infer_relations", _n(infer_relations))
    graph.add_node("compile_spec", _n(compile_spec))
    graph.add_node("execute", _n(execute))
    graph.add_node("triage", _n(triage))
    graph.add_node("refine", _n(refine))
    graph.add_node("report", _n(report))

    graph.add_edge(START, "ingest_spec")
    graph.add_conditional_edges("ingest_spec", _dispatch_endpoints, ["infer_endpoint_rules"])
    graph.add_edge("infer_endpoint_rules", "infer_invariants")
    graph.add_edge("infer_invariants", "infer_relations")
    graph.add_edge("infer_relations", "compile_spec")
    graph.add_edge("compile_spec", "execute")
    graph.add_conditional_edges("execute", _route_after_execute, ["triage", "report"])
    graph.add_conditional_edges("triage", _route_after_triage, ["refine", "report"])
    graph.add_edge("refine", "compile_spec")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)
