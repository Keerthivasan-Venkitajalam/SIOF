"""Secure error types and response helpers for enterprise services."""

from __future__ import annotations

import logging
import traceback
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ErrorPayload:
    """Serializable error payload returned to clients."""

    code: str
    message: str
    correlation_id: str


class EnterpriseError(Exception):
    """Base enterprise exception with safe client-facing message."""

    def __init__(
        self,
        *,
        code: str,
        status_code: int,
        safe_message: str,
        internal_message: str | None = None,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ):
        self.code = code
        self.status_code = status_code
        self.safe_message = safe_message
        self.internal_message = internal_message or safe_message
        self.details = details or {}
        self.correlation_id = correlation_id or str(uuid.uuid4())
        super().__init__(self.internal_message)


def auth_error(*, correlation_id: str | None = None) -> EnterpriseError:
    return EnterpriseError(
        code="authentication_failed",
        status_code=401,
        safe_message="Authentication failed",
        internal_message="Authentication failed",
        correlation_id=correlation_id,
    )


def forbidden_error(*, correlation_id: str | None = None) -> EnterpriseError:
    return EnterpriseError(
        code="forbidden",
        status_code=403,
        safe_message="Forbidden",
        internal_message="Authorization denied",
        correlation_id=correlation_id,
    )


def validation_error(message: str, *, correlation_id: str | None = None) -> EnterpriseError:
    return EnterpriseError(
        code="validation_error",
        status_code=400,
        safe_message=message,
        internal_message=message,
        correlation_id=correlation_id,
    )


def internal_error(
    *,
    message: str = "Internal Server Error",
    correlation_id: str | None = None,
) -> EnterpriseError:
    return EnterpriseError(
        code="internal_error",
        status_code=500,
        safe_message="Internal Server Error",
        internal_message=message,
        correlation_id=correlation_id,
    )


def to_error_response(
    error: Exception, *, include_validation_details: bool = True
) -> tuple[int, dict[str, Any]]:
    """Convert internal exception to client-safe response payload."""
    if isinstance(error, EnterpriseError):
        payload: dict[str, Any] = {
            "error": {
                "code": error.code,
                "message": error.safe_message,
                "correlation_id": error.correlation_id,
            }
        }

        if include_validation_details and error.code == "validation_error" and error.details:
            payload["error"]["details"] = error.details

        # Always log internal error details server-side.
        logger.error(
            "Enterprise error: %s",
            error.internal_message,
            extra={
                "code": error.code,
                "status_code": error.status_code,
                "correlation_id": error.correlation_id,
                "details": error.details,
            },
        )
        return error.status_code, payload

    correlation_id = str(uuid.uuid4())
    logger.error(
        "Unhandled enterprise exception",
        extra={"correlation_id": correlation_id, "exception": str(error)},
    )
    logger.debug(traceback.format_exc())
    return 500, {
        "error": {
            "code": "internal_error",
            "message": "Internal Server Error",
            "correlation_id": correlation_id,
        }
    }
