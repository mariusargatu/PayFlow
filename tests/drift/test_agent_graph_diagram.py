"""Agent graph drift gate (Layer 1, visual system section 17.4).

The committed ``agent/graph.mmd`` is the load bearing picture of the property
generation graph (design section 7.4). This test regenerates the diagram from
``graph.get_graph().draw_mermaid()`` and compares it, as a normalized set of
edges, to the committed file. Building the graph needs no API key and makes no
LLM call. A mismatch means the graph shape changed: regenerate the diagram in
the same commit, or the build is red.
"""

from __future__ import annotations

from pathlib import Path

from agent.graph import build_graph

_MMD = Path(__file__).resolve().parents[2] / "agent" / "graph.mmd"


def _edges(mermaid: str) -> set[str]:
    """Normalize to the set of edge lines, ignoring styling and layout headers."""
    edges: set[str] = set()
    for line in mermaid.splitlines():
        stripped = line.strip().rstrip(";")
        if "-->" in stripped or "-.->" in stripped:
            edges.add(" ".join(stripped.split()))
    return edges


def test_agent_graph_diagram_matches_committed():
    generated = build_graph().get_graph().draw_mermaid()
    assert _MMD.exists(), (
        f"missing {_MMD.name}; regenerate it from build_graph().get_graph()."
        "draw_mermaid() and commit it with the change"
    )
    committed = _MMD.read_text(encoding="utf-8")

    live_edges = _edges(generated)
    committed_edges = _edges(committed)
    if live_edges != committed_edges:
        only_live = sorted(live_edges - committed_edges)
        only_committed = sorted(committed_edges - live_edges)
        raise AssertionError(
            "Agent graph drift: the compiled StateGraph and agent/graph.mmd "
            "disagree.\n"
            f"  edges only in the code: {only_live}\n"
            f"  edges only in graph.mmd: {only_committed}\n"
            "Regenerate agent/graph.mmd from build_graph().get_graph()."
            "draw_mermaid() in the same commit as the graph change. Generated "
            "diagram:\n"
            f"{generated}"
        )
