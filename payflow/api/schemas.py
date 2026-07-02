"""Request and response models for the OpenAPI contract."""

from __future__ import annotations

from pydantic import BaseModel, Field

# SQLite stores signed 64 bit integers; anything larger overflows at insert. Bound
# amounts at the schema so an out of range value is a structured 422, never a 500.
# strict=True rejects JSON booleans (true would otherwise coerce to 1).
MAX_AMOUNT = 2**63 - 1


class CreateAccountRequest(BaseModel):
    name: str


class CreateIntentRequest(BaseModel):
    merchant_account_id: str
    amount: int = Field(ge=1, le=MAX_AMOUNT, strict=True)


class CaptureRequest(BaseModel):
    amount: int | None = Field(default=None, ge=1, le=MAX_AMOUNT, strict=True)


class RefundRequest(BaseModel):
    amount: int | None = Field(default=None, ge=1, le=MAX_AMOUNT, strict=True)


class AccountResponse(BaseModel):
    id: str
    name: str
    type: str
    created_at: str


class BalanceResponse(BaseModel):
    account_id: str
    balance: int


class IntentResponse(BaseModel):
    id: str
    merchant_account_id: str
    amount: int
    state: str
    authorized_amount: int
    captured_amount: int
    refunded_amount: int
    created_at: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
