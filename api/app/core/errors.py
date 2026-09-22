"""Domain exceptions and their HTTP translation.

Handlers raise domain errors; one exception handler maps them to responses, so
status codes stay consistent and nothing leaks an internal message.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for expected, client-visible failures."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ValidationFailedError(AppError):
    # Literal rather than the Starlette constant, which was renamed between
    # versions (UNPROCESSABLE_ENTITY -> UNPROCESSABLE_CONTENT).
    status_code = 422
    code = "validation_failed"


class QuotaExceededError(AppError):
    """Plan limit or safety cap reached. Distinct from validation: retry later may succeed."""

    status_code = status.HTTP_402_PAYMENT_REQUIRED
    code = "quota_exceeded"


class SafetyBlockedError(AppError):
    """The safety engine refused an action (circuit open, outside hours, cap reached)."""

    status_code = status.HTTP_409_CONFLICT
    code = "safety_blocked"


class UpstreamError(AppError):
    """A third party (LinkedIn, Stripe, Anthropic, proxy) failed in a non-retryable way."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_error"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )
