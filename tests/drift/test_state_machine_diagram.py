"""State machine drift gate (Layer 1, visual system §17.4).

The mermaid diagram in specs/state-machine.md is load bearing: it must agree
with the transition table the domain layer actually enforces. This test
regenerates the transition set from ``payflow.domain.state_machine`` and
compares it, as a set of edges, to the diagram parsed out of
specs/state-machine.md. That file is read only here; a mismatch means either the
code drifted or the spec did, and the spec only moves through an ADR.
"""

from __future__ import annotations

import re
from pathlib import Path

from payflow.domain import state_machine as sm
from payflow.domain.models import State

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = _REPO_ROOT / "specs" / "state-machine.md"

_START = "[*]"

# A capture or refund resolves its target through the domain result functions;
# authorize and void land on fixed states in the service. Exercising the result
# functions on a draining and a non draining amount surfaces both branches.
_AUTHORIZED_AMOUNT = 100
_NON_DRAINING = 40


def _capture_targets() -> set[State]:
    return {
        sm.state_after_capture(_AUTHORIZED_AMOUNT, _AUTHORIZED_AMOUNT),
        sm.state_after_capture(_AUTHORIZED_AMOUNT, _NON_DRAINING),
    }


def _refund_targets() -> set[State]:
    return {
        sm.state_after_refund(_AUTHORIZED_AMOUNT, _AUTHORIZED_AMOUNT),
        sm.state_after_refund(_AUTHORIZED_AMOUNT, _NON_DRAINING),
    }


_OPERATIONS = (
    (sm._AUTHORIZE_FROM, {State.AUTHORIZED}),
    (sm._CAPTURE_FROM, _capture_targets()),
    (sm._VOID_FROM, {State.VOIDED}),
    (sm._REFUND_FROM, _refund_targets()),
)


def domain_transitions() -> set[tuple[str, str]]:
    """Edges the domain enforces, plus derived start and terminal markers.

    Self loops (a partial capture or refund that does not advance the state) are
    omitted to match the spec diagram's convention of showing only state
    advancing transitions.
    """
    edges: set[tuple[str, str]] = set()
    for from_states, targets in _OPERATIONS:
        for source in from_states:
            for target in targets:
                if source != target:
                    edges.add((source.value, target.value))

    sources = {src for src, _ in edges}
    targets = {dst for _, dst in edges}
    all_states = sources | targets
    for initial in all_states - targets:
        edges.add((_START, initial))
    for terminal in all_states - sources:
        edges.add((terminal, _START))
    return edges


def _sort_key(edge: tuple[str, str]) -> tuple[int, str, int, str]:
    src, dst = edge
    return (0 if src == _START else 1, src, 0 if dst == _START else 1, dst)


def render_mermaid(edges: set[tuple[str, str]]) -> str:
    lines = ["stateDiagram-v2"]
    for src, dst in sorted(edges, key=_sort_key):
        lines.append(f"    {src} --> {dst}")
    return "\n".join(lines)


def spec_transitions() -> set[tuple[str, str]]:
    text = _SPEC.read_text(encoding="utf-8")
    match = re.search(r"```mermaid\n(.*?)```", text, re.DOTALL)
    assert match, "no mermaid block found in specs/state-machine.md"
    block = match.group(1)
    assert (
        "stateDiagram-v2" in block
    ), "specs/state-machine.md mermaid block is not a stateDiagram-v2"

    edges: set[tuple[str, str]] = set()
    for line in block.splitlines():
        edge = re.match(r"\s*(\S+)\s*-->\s*(\S+)\s*$", line)
        if edge:
            edges.add((edge.group(1), edge.group(2)))
    return edges


def test_state_machine_diagram_matches_domain():
    generated = domain_transitions()
    documented = spec_transitions()
    if generated != documented:
        only_in_code = sorted(generated - documented)
        only_in_spec = sorted(documented - generated)
        message = (
            "State machine drift: the specs/state-machine.md diagram and the "
            "domain transition table disagree.\n"
            f"  transitions only in the code:            {only_in_code}\n"
            f"  transitions only in specs/state-machine: {only_in_spec}\n"
            "Either the code is wrong or the spec is, and the spec only changes "
            "through a superseding ADR. Regenerated diagram from the code:\n"
            f"{render_mermaid(generated)}"
        )
        raise AssertionError(message)
