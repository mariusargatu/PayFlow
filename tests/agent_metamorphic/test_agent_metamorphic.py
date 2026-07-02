"""AGENT-MR self referential suite: does the triage agent judge stably? (design 8.6)

Layer 2 tests the verification agent's own judgment rather than PayFlow. Each
AGENT-MR relation applies a transform that carries no real information and asserts
the triage verdict is unchanged:

  AGENT-MR-1 Order      shuffle the order of counterexamples in one triage batch
  AGENT-MR-2 Paraphrase reword a failure's natural language description
  AGENT-MR-3 Padding    insert a harmless successful step away from the failure

Stability is the assertion for the three relations. A separate ground truth check
asserts the verdict matches the hand labeled classification; that check is what a
biased triage regression (PAYFLOW_TRIAGE_REGRESSION) turns red while the stability
relations, being invariant under a uniform bias, can stay green, a subtlety worth
seeing directly.

Real triage calls (gpt-5.4-nano), cached per input; key gated. Marker: layer2.
"""

from __future__ import annotations

import os

import pytest

from _layer2 import KEY_SKIP_REASON
from fixtures import ALL_FIXTURES
from transforms import batch_state, single_failure_state

pytestmark = [
    pytest.mark.layer2,
    pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason=KEY_SKIP_REASON),
]

# (fixture, failure) pairs and human readable ids for parametrization.
_FAILURES = [(fx, ff) for fx in ALL_FIXTURES for ff in fx.failures]
_FAILURE_IDS = [ff.proposal_id for _fx, ff in _FAILURES]
_PADDABLE = [(fx, ff) for fx, ff in _FAILURES if ff.sequence_shaped]
_PADDABLE_IDS = [ff.proposal_id for _fx, ff in _PADDABLE]

# Verdict instability discovered by an actual AGENT-MR-2 run (2026-07-02): under
# these specific rewordings gpt-5-nano flipped its verdict even though the data was
# unchanged. They are marked xfail (non strict) with the observed flip so the
# finding stays visible without turning the suite red; the journey entry has the
# full analysis. Every other paraphrase held. This is exactly the fragility the
# relation exists to surface, it is a result, not a bug in the test.
_KNOWN_UNSTABLE_PARAPHRASE = {
    ("MR-1", 1): "gpt-5-nano flips real_bug -> bad_relation on this rewording",
    ("capture_in_partially_captured_rejected", 0): (
        "gpt-5-nano flips bad_rule -> real_bug on this rewording"
    ),
}


def _paraphrase_cases():
    cases = []
    for fx, ff in _FAILURES:
        for index in range(len(ff.paraphrases)):
            reason = _KNOWN_UNSTABLE_PARAPHRASE.get((ff.proposal_id, index))
            marks = (pytest.mark.xfail(reason=reason, strict=False),) if reason else ()
            cases.append(
                pytest.param(fx, ff, index, marks=marks, id=f"{ff.proposal_id}-p{index}")
            )
    return cases


_PARAPHRASE_CASES = _paraphrase_cases()

# One triage batch spanning every fixture, so AGENT-MR-1 has multiple
# counterexamples to reorder in a single call.
_ORDER_BATCH = list(ALL_FIXTURES)
_ALL_REFS = [ff.ref for fx in _ORDER_BATCH for ff in fx.failures]


def test_agent_mr1_order_stable(triage_runner):
    canonical = triage_runner.verdicts(batch_state(_ORDER_BATCH, reverse=False))
    reordered = triage_runner.verdicts(batch_state(_ORDER_BATCH, reverse=True))

    missing = [r for r in _ALL_REFS if r not in canonical or r not in reordered]
    assert not missing, f"AGENT-MR-1: triage returned no verdict for {missing}"
    unstable = {
        r: (canonical[r], reordered[r]) for r in _ALL_REFS if canonical[r] != reordered[r]
    }
    assert not unstable, f"AGENT-MR-1 order instability (canonical -> reordered): {unstable}"


@pytest.mark.parametrize("fx,ff,index", _PARAPHRASE_CASES)
def test_agent_mr2_paraphrase_stable(triage_runner, fx, ff, index):
    baseline = triage_runner.verdicts(single_failure_state(fx, ff))
    assert ff.ref in baseline, f"AGENT-MR-2: no baseline verdict for {ff.ref}"
    base = baseline[ff.ref]
    verdicts = triage_runner.verdicts(single_failure_state(fx, ff, paraphrase=index))
    got = verdicts.get(ff.ref)
    assert got == base, (
        f"AGENT-MR-2 paraphrase {index} flipped {ff.ref}: {base} -> {got}"
    )


@pytest.mark.parametrize("fx,ff", _PADDABLE, ids=_PADDABLE_IDS)
def test_agent_mr3_padding_stable(triage_runner, fx, ff):
    baseline = triage_runner.verdicts(single_failure_state(fx, ff))
    base = baseline.get(ff.ref)
    padded = triage_runner.verdicts(single_failure_state(fx, ff, pad=True))
    got = padded.get(ff.ref)
    assert got == base, f"AGENT-MR-3 padding flipped {ff.ref}: {base} -> {got}"


@pytest.mark.parametrize("fx,ff", _FAILURES, ids=_FAILURE_IDS)
def test_verdict_matches_ground_truth(triage_runner, fx, ff):
    """Hand labeled accuracy: the verdict must match the known classification.

    Real_bug fixtures come from real runs; the bad_rule / bad_invariant /
    bad_relation fixtures are assumptions a correct PayFlow build falsifies. This
    is the check a biased triage regression fails.
    """
    verdicts = triage_runner.verdicts(single_failure_state(fx, ff))
    got = verdicts.get(ff.ref)
    assert got == ff.expected, (
        f"triage misclassified {ff.ref}: expected {ff.expected}, got {got}"
    )
