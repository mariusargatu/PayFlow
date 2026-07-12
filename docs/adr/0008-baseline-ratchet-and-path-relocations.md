# ADR-0008: Ratchet the mutation baseline to 73.1% and record two path relocations

**Date:** 2026-07-12
**Status:** Accepted. Supersedes the threshold table in [ADR-0003](0003-mutation-thresholds.md); records relocations of paths named in the immutable [ADR-0001](0001-foundational-decisions.md) without editing it.

## Context

Two facts drifted from what the decision records say, and this project's own rule is that a decision changes through a superseding ADR, never a silent edit (ADR-0001 is immutable, and the mutation thresholds live in ADR-0003). This ADR closes both.

1. **The mutation baseline moved.** ADR-0003 set the healthy line at the then measured 65.3% headline kill rate. On 2026-07-11 the discovered suite gained two once per example oracles it had been missing: global conservation (INV-4) and full non negativity across merchant, holds, and platform_fees (INV-3), closed by feeding the semantic explorer's survivors back through discovery. The baseline was recomputed and now reads 73.1% (385 killed of 527 covered, `mutation/baseline.json`); the agent discovered suite now matches the full local suite exactly, so the hand written sanity machine adds zero marginal kills. No ADR recorded the move.

2. **Two paths named in ADR-0001 no longer exist at those names.** ADR-0001 decision 1 names a repo root `spec.md` and a root `.importlinter`. Both were relocated during the build, and ADR-0001, being immutable, still points at the old names, so a reader following those paths finds nothing.

## Decisions

1. **Ratchet the healthy mutation line to the measured 73.1% baseline**, keeping ADR-0003's shape (a roughly ten point block gap below the baseline so a real regression trips without flapping on the reduced budget noise) and its ratchet only rule (the bar goes up as the agent discovers more, never down to turn a red run green):

   | Band | Headline kill rate | CI behaviour |
   |---|---|---|
   | block | below 63% | nightly turns red (once gating is enabled) |
   | warn | 63% to below 73% | nightly warns, tracked over time |
   | healthy | 73% or above | no action |

   These still gate the headline number and stay warn only per design section 10 until the number proves stable across a few nightly recomputes. The move from 65.3% to 73.1% is a semantic coverage gain (a real missing oracle added), not a threshold loosened to pass: mutmut rarely produces a conservation breaking mutant, so the syntactic kill rate rose only modestly while the frozen spec coverage rose from 4 of 12 fully asserted to 6 of 12.

2. **Record the two relocations, so ADR-0001's paths resolve** (the invariant source rule is unchanged and simply attaches to the new locations):
   - The repo root `spec.md` is now the `specs/` folder, split by concern into `domain.md`, `api.md`, `state-machine.md`, `invariants.md`, and `constraints.md`. Still frozen, still the single source of truth for PayFlow behaviour, still changed only through an ADR.
   - The Layer 0 contracts, intended for a root `.importlinter`, live in `pyproject.toml` under `[tool.importlinter]`. The root `.importlinter` path was itself deny listed for agents, which blocked its own creation, so the equivalent table in `pyproject.toml` is the canonical location. A drift gate (`tests/drift/test_importlinter_contracts.py`) guards it against silent edits, and the block only ever gets stronger.

## Consequences

- The README headline (73.1%) and the threshold bands now have a decision record; `tests/drift/test_public_numbers.py` already pins the published kill rate to `mutation/baseline.json`, so the number and its record cannot drift apart silently.
- ADR-0001 stays byte for byte immutable, including its prose style: it is a historical record, not a living document, so the no em dash and no hyphenated word writing convention applied to the rest of the docs deliberately stops at its edge.
- The next coverage gain (INV-7, the amount and fee boundary rules, or cross endpoint idempotency) ratchets the healthy line again through this same mechanism.
