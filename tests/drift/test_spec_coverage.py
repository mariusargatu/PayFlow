"""Spec-coverage gate: the gate on the gate.

The merge-blocking Layer 1 suite is ``generated_specs/`` -- an agent-authored,
nondeterministically-regenerated snapshot. It has already, on one discovery run,
dropped INV-4/INV-7 and narrowed INV-3. Nothing stopped that, and nothing stops
the next ``uv run agent-run`` from dropping an oracle again. That silent
degradation of the gate is the exact failure mode this whole project exists to
prevent, so it deserves a gate of its own.

This test enforces three things, all mechanical and green today:

1. **Anchored to the frozen spec.** The coverage inventory (``mutation/spec_coverage.json``)
   must account for exactly the INV-1..7 declared in ``specs/invariants.md`` -- no
   frozen invariant can be silently dropped from the inventory.
2. **Covered stays covered.** Every rule the inventory marks as having an oracle
   (coverage != ``absent``) must still have its assertion present in
   ``generated_specs/``. A regeneration that drops a committed oracle fails here.
3. **Coverage only strengthens.** The set of rules with no oracle may only shrink
   from the committed floor below; it may never grow. Downgrading a covered rule
   to ``absent`` to dodge check 2 fails this check.

This is distinct from ``spec_coverage.json``'s own *semantic* classification
(full / narrowed / partial), which stays human-adjudicated and informational per
ADR-0007. This gate is the mechanical presence-and-monotonicity floor underneath
that judgment. Raising the floor (adding an INV-4/INV-7 oracle) is a deliberate,
reviewed edit here plus the new assertion in ``generated_specs/`` -- the ratchet
turns one way.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INVARIANTS_MD = _REPO_ROOT / "specs" / "invariants.md"
_COVERAGE = _REPO_ROOT / "mutation" / "spec_coverage.json"
_GENERATED = (
    _REPO_ROOT / "generated_specs" / "payflow_spec.py",
    _REPO_ROOT / "generated_specs" / "payflow_mr.py",
)

# The committed floor: rules that have no oracle in the discovered suite today.
# A regeneration may REMOVE entries here (by adding the missing oracle and its
# marker below) but may never ADD one. Each is a known, published gap in the
# trust report's coverage matrix; closing one is the hardening work. INV-4
# (conservation) and INV-3 (full non-negativity) were closed on 2026-07-11.
_COVERAGE_FLOOR_ABSENT = frozenset(
    {"INV-7", "amount ≥ 1", "capture > fee", "idempotency"}
)

# For each rule the inventory claims IS covered, substrings that must all appear in
# the committed generated_specs/ for that oracle to actually exist. These are
# CONTENT markers (the assertion text the compiler owns), not the agent's [INV-n]
# id tags: the agent labels its own invariants, and those labels do not always
# match the frozen numbering (e.g. it may call conservation "INV-3"), so anchoring
# on the enacted assertion is what stays stable across nondeterministic
# regenerations. A regeneration that no longer produces one of these has changed
# what the blocking gate checks, which is a human-review signal, not a silent pass.
_ORACLE_MARKERS = {
    "INV-1": ('captured_amount"] <= body["authorized_amount"]',),
    "INV-2": ('refunded_amount"] <= body["captured_amount"]',),
    # The nonneg assertion message itself. The earlier markers ("system account",
    # "acct_platform_fees") were satisfied by the CONSERVATION check's scaffolding (a
    # "shared system accounts" comment and the _system_accounts tuple), so a spec that
    # dropped the nonneg oracle but kept conservation passed silently. Found on a real
    # regenerated spec regression, 2026-07-12: anchor on the assertion, not on nearby words.
    "INV-3": ("balance is negative",),
    "INV-4": ("money not conserved",),                  # global debits == credits
    "INV-5": ("_illegal_state_rejected",),
    "INV-6": ("_illegal_state_rejected", "_assert_unchanged"),
    "capture ≤ remaining": ("over remaining",),
    "refund ≤ refundable": ("over refundable",),
}


def _frozen_invariant_ids() -> set[str]:
    return set(re.findall(r"INV-\d+", _INVARIANTS_MD.read_text(encoding="utf-8")))


def _coverage() -> dict:
    return json.loads(_COVERAGE.read_text(encoding="utf-8"))


def _all_rules(cov: dict) -> list[dict]:
    return list(cov.get("invariants", [])) + list(cov.get("boundary_rules", []))


def _generated_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _GENERATED if p.exists())


def test_coverage_inventory_accounts_for_every_frozen_invariant():
    frozen = _frozen_invariant_ids()
    inventoried = {inv["id"] for inv in _coverage().get("invariants", [])}
    assert frozen == inventoried, (
        "spec_coverage.json invariant inventory drifted from specs/invariants.md: "
        f"frozen but uninventoried {sorted(frozen - inventoried)}, "
        f"inventoried but not frozen {sorted(inventoried - frozen)}. "
        "Every frozen invariant must appear in the coverage inventory so its "
        "oracle presence is tracked."
    )


def test_uncovered_set_only_shrinks_from_the_committed_floor():
    absent_now = {r["id"] for r in _all_rules(_coverage()) if r["coverage"] == "absent"}
    grew = absent_now - _COVERAGE_FLOOR_ABSENT
    assert not grew, (
        f"coverage regressed: {sorted(grew)} now have no oracle but were covered at "
        "the committed floor. A regenerated spec may only strengthen coverage. If "
        "this is a deliberate, ADR-backed spec change, update _COVERAGE_FLOOR_ABSENT "
        "in the same commit; otherwise re-run discovery until the oracle returns."
    )


def test_money_oracles_cite_the_frozen_spec_id():
    """The rendered failure message is a contract: it must name the FROZEN id.

    A coding agent reads "[INV-4] money not conserved" and acts on it, so an
    oracle that cited the wrong number would send a fix at the wrong rule. The
    agent numbers its own proposals freely (it has called conservation "INV-3"),
    so render._CANONICAL_INV_ID pins the public id by invariant kind: conservation
    is INV-4, non-negativity is INV-3 (specs/invariants.md). A presence check
    cannot catch a swap (both tags stay present), so this asserts co-occurrence on
    the offending line itself.
    """
    for line in _generated_text().splitlines():
        if "money not conserved" in line:
            assert "[INV-4]" in line, (
                f"conservation oracle must cite [INV-4] per specs/invariants.md, got: {line.strip()}"
            )
        if "balance is negative" in line:
            assert "[INV-3]" in line, (
                f"non-negativity oracle must cite [INV-3] per specs/invariants.md, got: {line.strip()}"
            )


def test_every_covered_rule_still_has_its_oracle_in_generated_specs():
    text = _generated_text()
    assert text, "generated_specs/ is empty or missing; run uv run agent-run"
    missing = {}
    for rule in _all_rules(_coverage()):
        if rule["coverage"] == "absent":
            continue
        rid = rule["id"]
        markers = _ORACLE_MARKERS.get(rid)
        assert markers is not None, (
            f"{rid} is marked covered ({rule['coverage']}) but has no marker in "
            "_ORACLE_MARKERS; add the assertion substring that proves its oracle exists"
        )
        absent_markers = [m for m in markers if m not in text]
        if absent_markers:
            missing[rid] = absent_markers
    assert not missing, (
        "covered rules whose oracle is no longer present in generated_specs/: "
        f"{missing}. A regeneration dropped an assertion the committed spec used to "
        "carry; the blocking gate is now weaker than the coverage inventory claims. "
        "Re-run discovery until it returns, or route the survivor back through the loop."
    )
