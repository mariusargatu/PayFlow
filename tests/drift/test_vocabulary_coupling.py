"""Vocabulary-coupling drift gate.

The property-generation agent may only propose members of a few closed
vocabularies (``schemas.InvariantKind``, ``TransformKind``, ``Effect``). The
deterministic compiler owns the concrete enactment of every member: an invariant
kind maps to a template in ``render._INVARIANTS``, a transform to one in
``render_mr._TEST_TEMPLATES``, and each is glossed in ``tools.labels`` for the
trust report.

The hazard this gate closes: those maps are separate dicts from the schema
``Literal``s, so adding a vocabulary member without its template used to render to
an empty string and pass *vacuously* -- a silent hole in the Layer 1 gate (the
render functions now raise instead, but only at generation time, which the keyless
PR lane never exercises). This test is the static complement: it fails the build
the moment a closed vocabulary and its enactment/label maps fall out of lockstep,
so the codegen the whole trust chain runs through cannot grow a hole while still
passing green.
"""

from __future__ import annotations

from typing import get_args

from agent import schemas
from agent.codegen import render, render_mr
from tools import labels

# Effects that act on an existing intent; ``none`` is a read/setup step with no
# transition rule and no legal-state default, so it is excluded from the maps that
# only cover acting effects.
_ACTING_EFFECTS = frozenset(get_args(schemas.Effect)) - {"none"}


def test_every_invariant_kind_has_a_render_template():
    kinds = set(get_args(schemas.InvariantKind))
    templates = set(render._INVARIANTS)
    assert kinds == templates, (
        "schemas.InvariantKind and render._INVARIANTS drifted: "
        f"missing template for {sorted(kinds - templates)}, "
        f"orphan template for {sorted(templates - kinds)}. "
        "A new InvariantKind must ship with its template, or the generated spec "
        "renders it to nothing and passes vacuously."
    )


def test_every_transform_kind_has_an_mr_template():
    kinds = set(get_args(schemas.TransformKind))
    templates = set(render_mr._TEST_TEMPLATES)
    assert kinds == templates, (
        "schemas.TransformKind and render_mr._TEST_TEMPLATES drifted: "
        f"missing template for {sorted(kinds - templates)}, "
        f"orphan template for {sorted(templates - kinds)}."
    )


def test_every_acting_effect_has_a_legal_state_default():
    missing = _ACTING_EFFECTS - set(render._EFFECT_LEGAL_DEFAULT)
    assert not missing, (
        f"acting effects with no render._EFFECT_LEGAL_DEFAULT entry: {sorted(missing)}"
    )


def test_every_vocabulary_member_has_a_plain_english_label():
    # The trust report decomposes each proposed check into a layperson sentence via
    # tools.labels; an unmapped member is silently skipped, so the funnel would
    # under-report what the suite verifies. Require full coverage of the two kinds
    # the report renders (invariants, transforms) and the acting effects.
    checks = {
        "InvariantKind": (get_args(schemas.InvariantKind), labels._INVARIANT_PLAIN),
        "TransformKind": (get_args(schemas.TransformKind), labels._TRANSFORM_PLAIN),
        "Effect (acting)": (sorted(_ACTING_EFFECTS), labels._EFFECT_PLAIN),
    }
    problems = {
        name: sorted(set(members) - set(plain))
        for name, (members, plain) in checks.items()
        if set(members) - set(plain)
    }
    assert not problems, f"vocabulary members with no plain-English label: {problems}"
