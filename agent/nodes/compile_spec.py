"""compile_spec node: render proposals into a runnable module (no LLM).

Writes the compiled RuleBasedStateMachine to ``generated_specs/`` (versioned,
committed) so the accepted Layer 1 spec is always a reviewable file, not a blob
inside a run log.
"""

from __future__ import annotations

from pathlib import Path

from ..codegen.render import render_module
from ..codegen.render_mr import render_mr_module
from ..state import AgentState


def _dedupe_last(rules):
    """Keep the last rule per operation so refined proposals win over their originals.

    ``proposed_rules`` accumulates through a reducer (the Send fan in and every
    refine pass append), so a corrected rule shares its predecessor's operation_id
    (refine preserves both name and operation_id) and must shadow it here. Keying on
    operation_id, not name, means two endpoints the model happened to give the same
    name do not collapse into one and silently drop an operation from the spec.
    """
    seen: dict[str, object] = {}
    for rule in rules:
        seen[rule.operation_id or rule.name] = rule
    return list(seen.values())


def compile_spec(state: AgentState, deps) -> dict:
    rules = _dedupe_last(state.get("proposed_rules", []))
    invariants = state.get("proposed_invariants", [])
    relations = state.get("proposed_relations", []) or []
    source = render_module(
        rules,
        invariants,
        max_examples=deps.config.max_examples,
        step_count=deps.config.stateful_step_count,
    )
    path = Path(deps.generated_spec_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")

    out = {
        "generated_spec_code": source,
        "generated_spec_path": str(path),
    }
    note = (
        f"compile_spec: rendered {len(rules)} rules + {len(invariants)} invariants "
        f"to {path}"
    )
    # The MR module is only rendered once relations exist (Phase 3+). A Phase 2
    # style run with no proposed relations still compiles the rule/invariant spec
    # alone, so the pipeline stays runnable at either scope.
    if relations:
        mr_source = render_mr_module(relations, max_examples=deps.config.mr_max_examples)
        mr_path = Path(deps.generated_mr_path)
        mr_path.parent.mkdir(parents=True, exist_ok=True)
        mr_path.write_text(mr_source, encoding="utf-8")
        out["generated_mr_code"] = mr_source
        out["generated_mr_path"] = str(mr_path)
        note += f"; {len(relations)} relations to {mr_path}"
    out["history"] = [note]
    return out
