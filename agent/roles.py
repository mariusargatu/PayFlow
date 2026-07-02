"""The propose/dispose split, as one declared source of truth (design section 7.1).

The whole trust argument rests on one boundary: the LLM PROPOSES (fallible), and
a deterministic engine DISPOSES (trustworthy) by compiling, executing, scoring,
and reporting. Every graph node is exactly one of the two. Prose alone lets that
boundary blur, so it is declared here once and used everywhere: it tags the
LangWatch spans, colours the run views, and fills the design section 7.3 role
column, and a drift gate (tests/drift/test_node_roles.py) asserts this map covers
exactly the graph's nodes so it cannot silently rot.
"""

from __future__ import annotations

PROPOSE = "propose"  # an LLM call whose output must be disposed by something else
DISPOSE = "dispose"  # deterministic: parse, compile, execute, score, report

# One entry per graph node (agent/graph.py). The propose nodes are exactly the
# ones that call the LLM; the dispose nodes never do.
NODE_ROLES: dict[str, str] = {
    "ingest_spec": DISPOSE,          # parse the OpenAPI document
    "infer_endpoint_rules": PROPOSE,  # LLM proposes a rule per endpoint
    "infer_invariants": PROPOSE,      # LLM proposes system wide invariants
    "infer_relations": PROPOSE,       # LLM proposes metamorphic relations
    "compile_spec": DISPOSE,          # deterministic codegen to a Hypothesis module
    "execute": DISPOSE,               # Hypothesis falsifies against the live SUT
    "triage": PROPOSE,                # LLM classifies a failure (checked by Layer 2)
    "refine": PROPOSE,                # LLM rewrites the offending proposal
    "report": DISPOSE,                # deterministic: write artifacts and score
}

LABEL = {
    PROPOSE: "LLM proposes (fallible)",
    DISPOSE: "deterministic disposes (trustworthy)",
}


def role_of(node: str) -> str:
    """The role of a node; unknown nodes default to dispose (nothing LLM assumed)."""
    return NODE_ROLES.get(node, DISPOSE)


def nodes_with_role(role: str) -> list[str]:
    return [n for n, r in NODE_ROLES.items() if r == role]
