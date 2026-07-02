# PayFlow: Invariants

These must hold after every request, under any request sequence. The verification pipeline enforces them; the implementation should also make the load bearing ones locally obvious (DB constraints, guarded transitions).

| ID | Invariant |
|---|---|
| INV-1 | `captured_amount ≤ authorized_amount` at all times |
| INV-2 | `refunded_amount ≤ captured_amount` at all times |
| INV-3 | No balance of any `merchant`, `holds`, or `platform_fees` account is ever negative; only `external_settlement` may go negative |
| INV-4 | Sum of all ledger debits equals sum of all ledger credits, globally, at all times |
| INV-5 | State changes only along the state machine table; nothing is reachable from `VOIDED` or `REFUNDED` |
| INV-6 | The state machine preconditions are enforced: an illegal operation returns `409` and changes nothing, no state change, no ledger entries |
| INV-7 | Every intent in state `AUTHORIZED` or beyond has at least one ledger entry pair carrying its `payment_intent_id` |

The catalog of metamorphic relations (MR-1 and following) that exercise these invariants lives in `docs/design.md` §5.6; it is not duplicated here.
