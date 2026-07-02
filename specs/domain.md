# PayFlow: Domain

## What PayFlow is

PayFlow is a payment intent processor backed by a double entry ledger: a customer facing state machine on top, bookkeeping underneath. Every movement of money is a balanced pair of ledger entries (one debit, one credit, equal amounts). It is a single process HTTP service (FastAPI, SQLite) with no external dependencies.

All monetary amounts are **integers in minor units** (cents). No floats anywhere in the money path. There is a single, implicit currency; amounts carry no currency field.

## Accounts and the ledger

### Account types

| Account | Created by | May go negative? |
|---|---|---|
| `merchant` accounts | `POST /accounts` | No |
| `external_settlement` | seeded at startup, exactly one | **Yes**, it represents the outside world (card networks, customer funds); money enters and leaves the system through it |
| `platform_fees` | seeded at startup, exactly one | No |
| `holds` | seeded at startup, exactly one | No |

The three system accounts have well known stable IDs (`acct_external_settlement`, `acct_platform_fees`, `acct_holds`). Merchant account IDs are server generated, prefixed `acct_`.

### Ledger entries

A ledger entry pair records: `debit_account`, `credit_account`, `amount` (integer > 0), `payment_intent_id` (nullable only for future non intent movements; every v1 pair carries one), `entry_type` (one of `authorize_hold`, `capture`, `capture_fee`, `hold_release`, `refund`), and a creation timestamp. Entries are **append only**: no update, no delete, corrections are new entries.

An account's balance is derived from the ledger (sum of credits minus sum of debits, or an equivalent maintained aggregate that the ledger can always reproduce).

### Ledger effect of each operation

All entries for one operation are written in **one atomic transaction**: either every pair lands or none does.

| Operation | Entry pairs written |
|---|---|
| create intent | none |
| authorize (amount `A`) | `authorize_hold`: debit `external_settlement` `A` -> credit `holds` `A` |
| capture (amount `C`) | `capture`: debit `holds` `C` -> credit merchant `C`; then `capture_fee`: debit `external_settlement` `fee` -> credit `platform_fees` `fee` (see fee model) |
| void (from `AUTHORIZED` / `PARTIALLY_CAPTURED`) | `hold_release`: debit `holds` (remaining hold, i.e. `authorized_amount - captured_amount`) -> credit `external_settlement` |
| void (from `CREATED`) | none |
| refund (amount `R`) | `refund`: debit merchant `R` -> credit `external_settlement` `R` |

Note the intent reaches `CAPTURED` only when captures have drained the hold to exactly zero (see the state machine), so there is never a hold remainder to release outside of void.

Fees are **not** returned on refund; because the fee was drawn from external settlement rather than the merchant, a full refund still returns the merchant to zero and no merchant balance ever goes negative (INV-3). See [ADR-0005](../docs/adr/0005-fee-from-settlement.md).

## Fee model

A single flat platform fee is charged on **every successful capture** (partial captures each incur it): configuration value `PAYFLOW_CAPTURE_FEE`, integer minor units, default `30`. The fee is posted as its own `capture_fee` pair (`external_settlement` -> `platform_fees`) in the same transaction as the capture pair, so the merchant keeps the full captured amount and the fee is borne by the settlement float. A capture whose amount is not greater than the fee is rejected (`422`): a platform business rule that a capture must be larger than the fee it generates. A fee of `0` writes no fee pair.
