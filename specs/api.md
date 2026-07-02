# PayFlow: API surface

Eight endpoints. All request/response bodies are JSON. FastAPI's generated OpenAPI document (`/openapi.json`) is the machine readable contract the verification agent consumes; every operation must carry an `operationId` (camelCase) and a `summary`.

| Method & path | Effect | Success |
|---|---|---|
| `POST /accounts` | Create a merchant account. Body: `{"name": str}` | `201`, account object |
| `GET /accounts/{id}/balance` | Current derived balance | `200`, `{"account_id": str, "balance": int}` |
| `POST /payment_intents` | Create an intent. Body: `{"merchant_account_id": str, "amount": int}` (`amount ≥ 1`) -> state `CREATED` | `201`, intent object |
| `POST /payment_intents/{id}/authorize` | Place the hold for the full intent amount | `200`, intent object |
| `POST /payment_intents/{id}/capture` | Body: `{"amount": int}`, optional; omitted means "capture the full remaining hold" | `200`, intent object |
| `POST /payment_intents/{id}/void` | Void; release any remaining hold | `200`, intent object |
| `POST /payment_intents/{id}/refund` | Body: `{"amount": int}`, optional; omitted means "refund everything captured and not yet refunded" | `200`, intent object |
| `GET /payment_intents/{id}` | Fetch current state | `200`, intent object |

The intent object: `{"id": str, "merchant_account_id": str, "amount": int, "state": str, "authorized_amount": int, "captured_amount": int, "refunded_amount": int, "created_at": str}`. Intent IDs are server generated, prefixed `pi_`.

## Idempotency

Every `POST` endpoint **requires** an `Idempotency-Key` header (any non empty string ≤ 255 chars); a missing key is a `422`. Semantics:

- **Same key, same endpoint, same payload** -> return a response identical to the first one (same status, same body), with **no new side effects**. Replayed any number of times, at any interval, there is exactly one underlying state change and one set of ledger entries.
- **Same key, different endpoint or different payload** -> `409` with error code `idempotency_conflict`. The original effect stands.
- Keys never expire in v1.

The uniqueness check and the side effect must be **atomic** (a single transaction or equivalent): two concurrent requests with the same key must not both execute the operation. This is tested under real concurrency; check then act implementations will fail the gate.

## Error contract

Errors are JSON: `{"error": {"code": str, "message": str}}`. `message` is human readable and must name the specific violation (the reader may be a coding agent fixing the call site). Codes and statuses:

| Status | `code` | When |
|---|---|---|
| `404` | `not_found` | Unknown account or intent ID |
| `409` | `invalid_state` | Operation not legal in the intent's current state (see the state machine) |
| `409` | `idempotency_conflict` | Idempotency payload/endpoint mismatch |
| `422` | `validation_error` | Malformed body, `amount < 1`, capture over remaining hold, refund over refundable amount, capture ≤ fee, missing idempotency key |
