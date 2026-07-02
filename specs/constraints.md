# PayFlow: Constraints

## Architectural constraints

Enforced structurally by `import-linter` (Layer 0) on every commit; these are gate failures, not style suggestions.

1. **Layering:** `payflow.api` -> `payflow.domain` -> `payflow.infrastructure`. Routes never import `infrastructure` directly; every state transition and every ledger write goes through the domain layer. Any new endpoint, forever, is forced through the same domain validation.
2. **Single writer to the ledger:** only `payflow.infrastructure.ledger.core` may write ledger rows. No other module imports the raw persistence session for ledger tables. Ledger atomicity is a property of one reviewable function, not a convention.
3. **Determinism seams:** wall clock time and ID generation go through injectable providers (a `clock` and an `id_generator` owned by the domain layer), not `datetime.now()` / `uuid4()` scattered at call sites. Property tests need to pin both.

## Deliberate bug toggles

The implementation ships with three env toggled seeded bugs, used by the verification pipeline as ground truth (each is the realistic broken version of a constraint or API rule). Reading `PAYFLOW_BUG` happens **once at startup**; unset means correct behavior. Never set in any merged configuration.

| Value | Required broken behavior |
|---|---|
| `fm_a` | Idempotency becomes check then act: look up the key, proceed if absent, insert afterwards, no atomicity with the side effect |
| `fm_b` | An extra route `POST /admin/payment_intents/{id}/force_capture` writes ledger entries directly from the API layer, bypassing `payflow.domain` (this toggle is a *build* time inclusion; the module exists only to be caught by Layer 0) |
| `fm_c` | The capture ledger pairs are written as separate commits instead of one transaction (debit committed, then credit), so a failure between them violates INV-4 |

## Do not invent

Out of scope for v1; implementing any of these is a spec violation, not initiative:

- Authentication, authorization, API keys, tenants.
- Multiple currencies, currency fields, or conversion.
- Disputes, chargebacks, or any state beyond the state machine.
- Webhooks, events, background jobs, async processing.
- Authorization expiry, scheduled captures, or any time driven behavior.
- Pagination, listing endpoints, filtering, search.
- Percentage or tiered fees; anything beyond the flat capture fee.
- Idempotency key expiry or scoping options.
- Configuration beyond `PAYFLOW_CAPTURE_FEE`, `PAYFLOW_BUG`, and the database path.
