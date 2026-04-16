"""Exception types raised by the VoxPact SDK."""

from __future__ import annotations

from typing import Any


class VoxpactError(Exception):
    """Base exception for all VoxPact SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response = response or {}


class AuthenticationError(VoxpactError):
    """Raised on 401 — invalid or expired API key / JWT."""


class PermissionError(VoxpactError):
    """Raised on 403 — valid credentials but insufficient permissions."""


class NotFoundError(VoxpactError):
    """Raised on 404 — the requested resource does not exist."""


class ValidationError(VoxpactError):
    """Raised on 400 / 422 — the request body failed validation."""


class RateLimitError(VoxpactError):
    """Raised on 429 — too many requests."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: int | None = None,
        status_code: int | None = None,
        response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response=response)
        self.retry_after = retry_after


class ServerError(VoxpactError):
    """Raised on 5xx — something went wrong on the VoxPact side."""


class PaymentError(VoxpactError):
    """Raised when a Stripe-related operation fails."""
