"""FastAPI application factory.

Wiring goes through ``domain.factory`` so the API layer never imports
infrastructure directly (enforced by Layer 0).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..config import Config, load_config
from ..domain.errors import PayFlowError, ValidationError
from ..domain.factory import build_service
from .routes import router


def _error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    app = FastAPI(title="PayFlow", version="0.1.0")
    app.state.config = config
    app.state.service = build_service(config)
    app.include_router(router)

    @app.exception_handler(PayFlowError)
    async def _payflow_error_handler(_: Request, exc: PayFlowError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=_error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in detail.get("loc", ()))
        message = detail.get("msg", "invalid request body")
        if location:
            message = f"{message} (at {location})"
        return JSONResponse(
            status_code=ValidationError.status,
            content=_error_body(ValidationError.code, message),
        )

    return app


app = create_app()
