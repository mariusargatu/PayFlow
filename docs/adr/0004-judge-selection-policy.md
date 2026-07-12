# ADR-0004: Judge selection policy

**Date:** 2026-07-02
**Status:** Accepted.

## Context

Layer 2 measured the triage judge (gpt-5-nano) as nondeterministically unstable, and a first run on gpt-5.4-mini produced a false positive real_bug verdict against a correct system (the void rule case). Both incidents shared a root cause split: missing evidence in the triage context, and verdict variance in the model. Neither size nor recency predicted judgment quality.

## Decisions

1. **Judges are selected empirically, never by size or recency.** The selection instrument is `tools/judge_comparison.py`: the Layer 2 fixture bank (accuracy against hand labeled ground truth, verdict stability across repeated runs, cost per verdict), including the historical void regression fixture. The winner is best quality per dollar; ties go to the cheaper model.
2. **Measured result (2026-07-02):** on the 6 fixture bank (5 Layer 2 fixtures plus the 1 void regression case, `tools/judge_comparison.py`), gpt-5.4-nano wins. It saturated the bank at accuracy 1.0 and stability 1.0 for $0.0008 per verdict; gpt-5.4 tied on quality at 12x the price; gpt-5.4-mini, the newest mid tier, scored worst (0.833 voted accuracy, 0.833 stability). Default set to `gpt-5.4-nano`. A perfect score on 6 fixtures is a saturated small bank, not proof of general accuracy: that is exactly why decision 4 keeps voting on and why the bank is load bearing and grows a fixture with every new misjudgment. The comparison is reproducible with `uv run python tools/judge_comparison.py` (budget guarded; it writes a fresh run report), so reselection is a command, not a claim.
3. **Triage runs with accepted slice annotations.** A deterministic pre triage step diffs each failing proposal against `generated_specs/accepted_proposals.json` and injects the disagreement as advisory evidence. This healed the void misjudgment on all four candidate models before any model change; evidence upgrades beat model upgrades and are attempted first.
4. **Triage verdicts are majority voted** (default 3, `PAYFLOW_TRIAGE_VOTES` env, ties escalate to `needs_human`). Voting is for visibility of the verdict distribution, not correctness: the comparison measured voting lowering accuracy on the unstable gpt-5.4-mini (raw 1.0, voted 0.833). Voting therefore never substitutes for selection by measurement.
5. **Refine rewrites are majority voted too**, on the same `triage_votes` count: a corrected proposal is regenerated N times and the plurality of its discriminating field (legal_states / kind / fee_handling) wins. This addresses non convergence caused by a nondeterministic judge landing the wrong correction on a single draw (observed on the void legal state rule); a tie takes the first ballot and the refine loop re votes next iteration.

## Consequences

- Any future judge change requires a fresh `judge_comparison` run committed as an artifact; "newer model available" is not a reason to switch.
- The fixture bank is now load bearing for model selection; new misjudgment incidents should be added to it as fixtures (as the void case was).
- Annotations only help where an acceptance history exists; genuinely novel proposals still ride on raw judgment, which is what the voting escalation path is for.
