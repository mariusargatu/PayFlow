# ADR-0001 — Foundational decisions

**Date:** 2026-07-01
**Status:** Accepted. **Immutable** — this file is deny-listed in `.claude/settings.json`; changing any decision here requires a new, superseding ADR, never an edit.

## Context

PayFlow is a demonstration of a trustworthy agentic SDLC: a coding agent implements a payment system from a frozen spec, and a four-layer verification pyramid (structural → behavioral → agent-judgment → mutation ground truth) is what makes that safe. The full design is `docs/design.md`. Before any code, the v2 design carried ten `OPEN` questions and several gaps (an untestable metamorphic relation, an unspecified fee model, underspecified accounts, a spec/design conflation). This ADR records how they were resolved on 2026-07-01.

## Decisions

1. **Two documents, two authorities.** The repo-root `spec.md` is the self-contained SUT spec the coding agent implements from; `docs/design.md` is the project/pipeline design. `spec.md` is frozen: the implementation conforms to the spec, never the reverse. Editing `spec.md` (or `.importlinter`, or this file) to make a gate pass is the exact failure mode this project exists to prevent, so all three are permission-deny-listed for agents.
2. **Cut multi-currency (old MR-4).** The API had no conversion surface, making the round-trip relation untestable as designed. Single implicit currency, integer minor units. The MR-4 ID is retired, not reused.
3. **Cut the `DISPUTED` state.** Its ledger semantics were unspecified and it added transitions without adding a new class of property. Seven states, two terminal. Disputes can return later as a deliberate spec-evolution exercise.
4. **Keep fees, and specify them.** A single flat per-capture platform fee (`PAYFLOW_CAPTURE_FEE`, default 30 minor units) posted to a seeded `platform_fees` account. This is the minimum model that keeps MR-3's "homogeneity with a known, bounded exception" relation meaningful — the deviation from exact scaling is computable: `(k−1) × fee × capture_count`.
5. **Specify the money-entry model.** Seeded system accounts (`external_settlement`, `platform_fees`, `holds`); authorize places a hold from external settlement, capture moves hold → merchant (fee → platform), void releases, refund returns. Only `external_settlement` may go negative. Closes the "balance endpoint with no funding source" gap.
6. **Concurrency harness in v1** (was `OPEN`). MR-5 idempotency under a check-then-act race (FM-A) is invisible to single-threaded Hypothesis. Phase 1 ships one deliberately dumb pytest: real HTTP server, N threads, one idempotency key, assert exactly one ledger movement.
7. **Deliberate bugs are a mechanism, not prose.** FM-A/B/C ship as env-toggled seeded bugs (`PAYFLOW_BUG=fm_a|fm_b|fm_c`), each paired with the layer that must catch it. They make the README's "layer X catches bug class Y" claims runnable and double as labeled ground truth for triage accuracy.
8. **Layer 2 at full weight, per design.** LangWatch tracing + `langwatch-scenario` + the self-referential AGENT-MR suite, in Phase 5. Cloud LangWatch free tier (OTel-native, so swappable).
9. **Remaining `OPEN` resolutions:** human merges (solo repo); same LLM family for implementer and verifier in v1 (adversarial diversity is a later experiment); `ingest_spec` is spec-only in v1 (no live probing); refine-loop budget is a constant 3; mutation scope is `payflow/domain` + ledger core; mutation-score *targets* stay open until a Phase 4 baseline exists; the nightly agent lane is manual-dispatch until an LLM API budget is wired into CI.
10. **Visual system is a first-class deliverable.** README front door, a `demo` command with one-screen gate summary, a generated single-file HTML trust report, and drift-gated diagrams (state machine + agent graph generated from code, gated by tests). Design §17.

## Consequences

- The coding agent has an unambiguous, implementable spec; ambiguity is an escalation, not a creative opportunity.
- Every cut is reversible and each reversal (disputes, multi-currency, adversarial models, live probing) is pre-framed as a future demonstration rather than lost scope.
- The project accepts weaker realism (no disputes, one currency, flat fees) in exchange for every remaining property being precisely testable — the trade this repo is *about*.
