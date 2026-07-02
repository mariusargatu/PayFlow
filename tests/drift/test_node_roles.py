"""Drift gate: the declared propose/dispose map must match the real graph.

The propose/dispose split (design section 7.1) is the project's trust argument, so
the claim "these nodes are the LLM, those are the deterministic engine" must not
silently drift. agent/roles.py is the declared truth (it tags the LangWatch
spans, colours the run views, and fills design section 7.3). This test asserts the
map covers exactly the graph's nodes and that every role is one of the two, so
adding or renaming a node without classifying it fails the build.
"""

from __future__ import annotations

from agent.graph import build_graph
from agent.roles import DISPOSE, NODE_ROLES, PROPOSE

_META_NODES = {"__start__", "__end__"}


def _graph_nodes() -> set[str]:
    graph = build_graph().get_graph()
    return {n for n in graph.nodes if n not in _META_NODES}


def test_role_map_covers_exactly_the_graph_nodes():
    graph_nodes = _graph_nodes()
    declared = set(NODE_ROLES)
    missing = graph_nodes - declared
    extra = declared - graph_nodes
    assert not missing and not extra, (
        "agent/roles.NODE_ROLES has drifted from the graph: "
        f"nodes missing a role {sorted(missing)}, roles for unknown nodes {sorted(extra)}. "
        "Every graph node must be declared propose or dispose (design 7.1)."
    )


def test_every_role_is_propose_or_dispose():
    bad = {n: r for n, r in NODE_ROLES.items() if r not in (PROPOSE, DISPOSE)}
    assert not bad, f"nodes with an invalid role: {bad}"
