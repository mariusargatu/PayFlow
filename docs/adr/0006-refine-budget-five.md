# ADR-0006: Refine budget raised to 5, and the relation refine prompt corrected

**Date:** 2026-07-02
**Status:** Accepted. Supersedes ADR-0001 decision 9 (refine budget of 3) in part.

## Context

ADR-0001 fixed the refine loop budget at 3 iterations. Discovery runs on
gpt-5.4-nano sometimes exhausted the budget with one proposal still failing,
most visibly MR-3 (scale_amounts), which surfaced the question of whether to
raise the budget. Investigation showed the budget was not the cause.

The real cause of the MR-3 non convergence was a stale prompt. The relation
refine system prompt (`agent/nodes/refine.py`) still told the model, from before
the fee from settlement change (ADR-0005), that "a transform that changes the
capture count (split, scale) needs fee_adjusted." Under ADR-0005 that is wrong
for scale: scaling amounts does not change the number of captures, the flat fee
is drawn from settlement rather than the merchant, and the merchant balance
scales cleanly, so the correct handling is exact_equivalence. Refine was being
instructed to give MR-3 the wrong answer, so no budget would have converged it.

## Decision

1. **Correct the relation refine prompt** to state the principle rather than a
   brittle enumeration: a relation is fee_adjusted only when its two runs perform
   a different number of captures (so platform_fees differs by the flat fee times
   that difference); when the capture count is preserved it is exact_equivalence.
   With this, refine flips MR-3 to exact_equivalence and it converges.
2. **Raise the refine budget from 3 to 5** (`agent/config.MAX_ITERATIONS`). This
   is headroom, not the MR-3 fix: the judge is nondeterministic (see the flaky
   judge finding behind ADR-0004), so some runs still trip on a legal state
   inference such as the void rule, and a few extra passes let more runs
   self correct before flagging for a human. Five stays far below the run's
   40 call budget guard, so a run cannot loop away real money.

## Consequences

- MR-3 converges reliably now that refine is told the correct fee principle.
- Runs converge more often overall; the escalation path after 5 passes is
  unchanged (flag, never silently accept).
- Legal state non convergence (void, refund) remains a known nondeterministic
  judge effect, not a budget limit; the committed accepted slice converged fully
  and is unchanged by this decision.
