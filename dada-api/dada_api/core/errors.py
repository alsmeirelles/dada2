"""Application exceptions and common FastAPI exception handlers."""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from dada_api.core.trace import trace_id_context

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """An expected API failure represented by the common error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the common error response with the active trace identifier."""
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "trace_id": trace_id_context.get() or "unavailable",
            }
        },
    )


def redact_validation_errors(
    errors: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Drop the submitted value from validation errors before returning them.

    Pydantic reports the rejected value under ``input``. Echoing it would leak
    passwords and other credentials into the response body, which the
    idempotency middleware then persists.

    Args:
        errors: Validation errors reported by Pydantic.

    Returns:
        The same errors without their ``input`` entries.
    """
    return [
        {key: value for key, value in error.items() if key != "input"}
        for error in errors
    ]


def install_exception_handlers(app: FastAPI) -> None:
    """Install handlers that normalize framework and application errors."""

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, error: ApiError) -> JSONResponse:
        return error_response(
            error.status_code,
            error.code,
            error.message,
            details=error.details,
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            422,
            "validation_error",
            "The request did not pass validation.",
            details={"errors": redact_validation_errors(error.errors())},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        detail = error.detail
        message = detail if isinstance(detail, str) else "The request failed."
        code = {
            401: "unauthenticated",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            413: "payload_too_large",
            429: "rate_limited",
            503: "service_unavailable",
        }.get(error.status_code, "request_error")
        return error_response(
            error.status_code,
            code,
            message,
            details={} if isinstance(detail, str) else {"detail": detail},
            headers=error.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled request error", exc_info=error)
        return error_response(500, "internal_error", "An unexpected error occurred.")
