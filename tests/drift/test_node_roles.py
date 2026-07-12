"""Drift gate: the declared propose/dispose map must match the real graph.

The propose/dispose split (design section 7.1) is the project's trust argument, so
the claim "these nodes are the LLM, those are the deterministic engine" must not
silently drift. agent/roles.py is the declared truth (it tags the LangWatch
spans, colours the run views, and fills design section 7.3). This test asserts the
map covers exactly the graph's nodes and that every role is one of the two, so
adding or renaming a node without classifying it fails the build.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent.graph import build_graph
from agent.roles import DISPOSE, NODE_ROLES, PROPOSE

_META_NODES = {"__start__", "__end__"}
_NODES_DIR = Path(__file__).resolve().parents[2] / "agent" / "nodes"


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


def _accesses_llm(node_name: str) -> bool:
    """True iff the node module accesses ``deps.llm`` (a real LLM call), found by
    AST so a comment like "no LLM here" never counts as one."""
    source = (_NODES_DIR / f"{node_name}.py").read_text(encoding="utf-8")
    return any(
        isinstance(n, ast.Attribute) and n.attr == "llm"
        for n in ast.walk(ast.parse(source))
    )


def test_dispose_nodes_never_call_the_llm_and_propose_nodes_do():
    """The propose/dispose boundary, enforced behaviourally, not only declared.

    The trust argument is that the LLM never marks its own homework: a dispose node
    compiles, executes, and scores deterministically, and must not call the model.
    ``test_role_map_covers_exactly_the_graph_nodes`` checks the labels match the
    graph; this checks the labels match the CODE, so a node cannot be tagged dispose
    while quietly calling ``deps.llm`` (nor tagged propose while never doing so).
    """
    wrong = {}
    for node, role in NODE_ROLES.items():
        calls = _accesses_llm(node)
        if role == DISPOSE and calls:
            wrong[node] = "declared dispose but accesses deps.llm"
        if role == PROPOSE and not calls:
            wrong[node] = "declared propose but never accesses deps.llm"
    assert not wrong, (
        f"propose/dispose labels contradict the code: {wrong}. A dispose node must "
        "never call the LLM (design section 7.1); fix the role or the node."
    )
