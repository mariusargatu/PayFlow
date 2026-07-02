# ADR-0003: Mutation scope and kill rate thresholds

**Date:** 2026-07-02 (Phase 4)
**Status:** Accepted. Closes the last `OPEN` item in design §15 ("Mutation-score targets").

## Context

Design §10 was explicit that gating on an unmeasured number is worse than not
gating at all, so mutation thresholds waited for a real Phase 4 baseline. ADR-0001
fixed the mutation *scope* at `payflow/domain` + the ledger core but left the
*target* open. Phase 4 measured the baseline, so both the exact scope and the
thresholds can now be set from data instead of guessed.

Two facts shaped the measurement:

1. **In process execution is mandatory.** mutmut only sees a mutated module inside
   the process that imported it. The committed agent specs drive PayFlow over HTTP
   against a uvicorn subprocess, which never sees the parent's mutations, so the
   baseline replays the exact committed specs with their transport swapped to an
   in process `TestClient` (`mutation/replay/`). The properties are byte for byte
   the agent's; only the wire changes.
2. **Full domain mutation is too broad and too slow.** Mutating all of
   `payflow/domain` generates ~834 mutants and runs well past the runtime cap. More
   importantly, most of that volume is not payment *logic*: `models.py` (data
   holders), `ports.py` (protocol stubs), `repositories.py` (SQLite adapters, ~197
   mutants of SQL/row mapping glue), and `factory.py` (composition root, ~67
   mutants of wiring) carry no branching decisions. A black box property suite that
   observes PayFlow only through its API cannot, and should not, distinguish a
   reordered SQL column from a correct one; those mutants are representation noise,
   not missed bugs.

## Decisions

1. **Scope narrows, within the ADR-0001 boundary, to the payment decision logic:**
   `service.py`, `state_machine.py`, `fees.py`, `idempotency.py`, and the ledger
   `core.py`. This is what design §11.1 means by "PayFlow core logic". The excluded
   modules stay excluded with the rationale above; the decision is recorded here so
   the narrowing is a deliberate, documented choice, not silent scope creep.
2. **The mutation sweep runs the committed properties at a reduced Hypothesis
   example budget and with shrinking disabled** (`mutation/replay/conftest.py`).
   Disabling shrink does not weaken detection at all (generation is unchanged; a
   failing mutant still fails, just without minimisation) and removes shrink induced
   CPU limit timeouts. The reduced example budget can only *miss* kills, never
   invent them, so the reported rate is a conservative floor.
3. **The measured baseline** (2026-07-02, `mutation/baseline.json`): headline
   **65.3%** kill rate (341 detected / 522 covered; 45 no test; 567 generated),
   agent discovered suites alone, zero hand written tests. The full local suite
   (agent + Phase 1 sanity machine) reaches 65.5%: the hand written suite adds
   exactly one kill, which is itself a result worth stating.

4. **Thresholds, set from that headline baseline:**

   | Band | Headline kill rate | CI behaviour |
   |---|---|---|
   | block | below 55% | nightly turns red (once gating is enabled) |
   | warn | 55% to below 65% | nightly warns, tracked over time |
   | healthy | 65% or above | no action |

   The block floor sits ~10 points below the baseline so a genuine regression trips
   it without flapping on the reduced budget noise; the healthy line is the measured
   baseline itself, so the bar can only ratchet up. These gate the **headline**
   number. They start **warn only** per design §10 (Layer 3 is warn only until a
   baseline exists, and this ADR is that baseline) and become blocking only after the
   number proves stable across a few nightly recomputes.

## Consequences

- The README headline is the headline kill rate from this baseline, marked as a
  local baseline that the nightly lane recomputes.
- Surviving mutants are triage material, not failures to paper over: the baseline
  commits the full survivor list, and the most instructive survivor is written up
  in the build log as a concrete "what property is missing" prompt.
- Raising the block threshold is the mechanism for ratcheting suite quality: the
  bar goes up as the agent discovers more relations, never down to make a red run
  green (the one rule in AGENTS.md).
