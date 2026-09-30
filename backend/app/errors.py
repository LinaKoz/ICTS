"""The one error shape used by every API response (§6):

    {"error": {"code": str, "message": str, "details": Any | None}}

`AppError` and its subclasses are the exception hierarchy the rest of
the backend raises. Route handlers (and deeper layers) raise these;
`register_exception_handlers` installs a FastAPI handler that turns
any `AppError` into the shape above with the right HTTP status.

Error codes are grouped by the families listed in §6:
- 400/404/401/403: general request errors
- 409: VERSION_CONFLICT, STALE_PREVIEW, ALREADY_CONFIRMED, WORKER_IN_USE,
  APPROVED_EDIT_NOT_ACKNOWLEDGED, ALREADY_APPROVED, NOT_APPROVED
- 413: FILE_TOO_LARGE, TOO_MANY_ROWS
- 415: unsupported content type on /imports
- 422: validation, HARD_VIOLATIONS, LOCKED_SHIFT, WARNINGS_NOT_ACKNOWLEDGED
- 429: GENERATION_IN_PROGRESS
- 500: ENGINE_ERROR
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for every error the application raises deliberately.

    Subclasses set `status_code` and `code`; `message` and `details`
    are provided per-instance.
    """

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


# --- 400/401/403/404: general request errors ---------------------------------


class BadRequestError(AppError):
    status_code = 400
    code = "BAD_REQUEST"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


# --- 409: conflicts ------------------------------------------------------------


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class VersionConflictError(ConflictError):
    code = "VERSION_CONFLICT"


class StalePreviewError(ConflictError):
    code = "STALE_PREVIEW"


class AlreadyConfirmedError(ConflictError):
    code = "ALREADY_CONFIRMED"


class WorkerInUseError(ConflictError):
    code = "WORKER_IN_USE"


class ApprovedEditNotAcknowledgedError(ConflictError):
    code = "APPROVED_EDIT_NOT_ACKNOWLEDGED"


class AlreadyApprovedError(ConflictError):
    code = "ALREADY_APPROVED"


class NotApprovedError(ConflictError):
    code = "NOT_APPROVED"


class StaleApprovalError(ConflictError):
    code = "STALE_APPROVAL"


# --- 413: request too large ------------------------------------------------


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "PAYLOAD_TOO_LARGE"


class FileTooLargeError(PayloadTooLargeError):
    code = "FILE_TOO_LARGE"


class TooManyRowsError(PayloadTooLargeError):
    code = "TOO_MANY_ROWS"


# --- 415: unsupported media type -----------------------------------------


class UnsupportedMediaTypeError(AppError):
    status_code = 415
    code = "UNSUPPORTED_MEDIA_TYPE"


# --- 422: validation / hard violations / locked shift ----------------------


class ValidationAppError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class HardViolationsError(ValidationAppError):
    code = "HARD_VIOLATIONS"


class LockedShiftError(ValidationAppError):
    code = "LOCKED_SHIFT"


class WarningsNotAcknowledgedError(ValidationAppError):
    """Approval with soft shortages needs acknowledge_warnings, a reason and the fingerprint (P11)."""

    code = "WARNINGS_NOT_ACKNOWLEDGED"


# --- 429: rate limiting ------------------------------------------------------


class GenerationInProgressError(AppError):
    status_code = 429
    code = "GENERATION_IN_PROGRESS"


# --- 500: engine / internal errors ------------------------------------------


class EngineError(AppError):
    status_code = 500
    code = "ENGINE_ERROR"


def register_exception_handlers(app: FastAPI) -> None:
    """Registers the FastAPI exception handler for `AppError`.

    Any `AppError` raised anywhere in a route is converted into the
    `{"error": {...}}` shape with its declared status code.
    """

    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default body is {"detail": [...]}; §6 has one shape.
        error = ValidationAppError(
            "the request is invalid",
            details=[{"loc": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()],
        )
        return JSONResponse(status_code=error.status_code, content=error.to_payload())
