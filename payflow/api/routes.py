"""The eight endpoints (specs/api.md). Each carries a camelCase operationId + summary."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..domain.errors import ValidationError
from ..domain.service import PaymentService
from .schemas import (
    AccountResponse,
    BalanceResponse,
    CaptureRequest,
    CreateAccountRequest,
    CreateIntentRequest,
    IntentResponse,
    RefundRequest,
)

router = APIRouter()


def _service(request: Request) -> PaymentService:
    return request.app.state.service


def _idempotency_key(request: Request) -> str:
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise ValidationError("missing required Idempotency-Key header")
    if len(key) > 255:
        raise ValidationError("Idempotency-Key header must be at most 255 characters")
    return key


@router.post(
    "/accounts",
    status_code=201,
    response_model=AccountResponse,
    operation_id="createAccount",
    summary="Create a merchant account",
)
def create_account(request: Request, body: CreateAccountRequest) -> JSONResponse:
    result = _service(request).create_account(_idempotency_key(request), body.name)
    return JSONResponse(status_code=result.status, content=result.body)


@router.get(
    "/accounts/{account_id}/balance",
    response_model=BalanceResponse,
    operation_id="getAccountBalance",
    summary="Get an account's current derived balance",
)
def get_account_balance(request: Request, account_id: str) -> JSONResponse:
    return JSONResponse(_service(request).get_balance(account_id))


@router.post(
    "/payment_intents",
    status_code=201,
    response_model=IntentResponse,
    operation_id="createPaymentIntent",
    summary="Create a payment intent",
)
def create_payment_intent(request: Request, body: CreateIntentRequest) -> JSONResponse:
    result = _service(request).create_intent(
        _idempotency_key(request), body.merchant_account_id, body.amount
    )
    return JSONResponse(status_code=result.status, content=result.body)


@router.post(
    "/payment_intents/{intent_id}/authorize",
    response_model=IntentResponse,
    operation_id="authorizePaymentIntent",
    summary="Authorize a payment intent, placing the hold",
)
def authorize_payment_intent(request: Request, intent_id: str) -> JSONResponse:
    result = _service(request).authorize(_idempotency_key(request), intent_id)
    return JSONResponse(status_code=result.status, content=result.body)


@router.post(
    "/payment_intents/{intent_id}/capture",
    response_model=IntentResponse,
    operation_id="capturePaymentIntent",
    summary="Capture all or part of an authorized payment intent",
)
def capture_payment_intent(
    request: Request, intent_id: str, body: CaptureRequest | None = None
) -> JSONResponse:
    amount = body.amount if body is not None else None
    result = _service(request).capture(_idempotency_key(request), intent_id, amount)
    return JSONResponse(status_code=result.status, content=result.body)


@router.post(
    "/payment_intents/{intent_id}/void",
    response_model=IntentResponse,
    operation_id="voidPaymentIntent",
    summary="Void a payment intent, releasing any remaining hold",
)
def void_payment_intent(request: Request, intent_id: str) -> JSONResponse:
    result = _service(request).void(_idempotency_key(request), intent_id)
    return JSONResponse(status_code=result.status, content=result.body)


@router.post(
    "/payment_intents/{intent_id}/refund",
    response_model=IntentResponse,
    operation_id="refundPaymentIntent",
    summary="Refund all or part of a captured payment intent",
)
def refund_payment_intent(
    request: Request, intent_id: str, body: RefundRequest | None = None
) -> JSONResponse:
    amount = body.amount if body is not None else None
    result = _service(request).refund(_idempotency_key(request), intent_id, amount)
    return JSONResponse(status_code=result.status, content=result.body)


@router.get(
    "/payment_intents/{intent_id}",
    response_model=IntentResponse,
    operation_id="getPaymentIntent",
    summary="Fetch a payment intent's current state",
)
def get_payment_intent(request: Request, intent_id: str) -> JSONResponse:
    return JSONResponse(_service(request).get_intent(intent_id))
