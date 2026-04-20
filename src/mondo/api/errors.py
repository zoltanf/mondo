"""Exception hierarchy and error-code mapping for the monday GraphQL API.

Mapping table is derived from monday-api.md §6 and plan.md §8.4. Every error
carries the `request_id` from `extensions` so users can quote it in bug reports
(monday's recommended troubleshooting handle since May 2025).
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, ClassVar


class ExitCode(IntEnum):
    """Process exit codes (plan §5.4). Stable contract — agents depend on these."""

    SUCCESS = 0
    GENERIC = 1
    USAGE = 2
    AUTH = 3
    RATE_LIMIT = 4
    VALIDATION = 5
    NOT_FOUND = 6
    NETWORK = 7
    TIMEOUT = 8


class MondoError(Exception):
    """Base exception. All monday API errors subclass this."""

    exit_code: ClassVar[ExitCode] = ExitCode.GENERIC

    def __init__(
        self,
        message: str,
        *,
        request_id: str | None = None,
        retry_in_seconds: int | None = None,
        code: str | None = None,
    ) -> None:
        self.request_id = request_id
        self.retry_in_seconds = retry_in_seconds
        self.code = code
        suffix = f" [request_id={request_id}]" if request_id else ""
        super().__init__(f"{message}{suffix}")


class RetryableError(MondoError):
    """Marker base for errors we can retry automatically."""

    exit_code = ExitCode.GENERIC


class AuthError(MondoError):
    exit_code = ExitCode.AUTH


class NotFoundError(MondoError):
    exit_code = ExitCode.NOT_FOUND


class UsageError(MondoError):
    exit_code = ExitCode.USAGE


class ValidationError(MondoError):
    exit_code = ExitCode.VALIDATION


class ColumnValueError(ValidationError):
    """422-ish: the supplied column value wasn't accepted by monday."""


class RateLimitError(RetryableError):
    """Minute-window rate limit hit (`Rate Limit Exceeded`)."""

    exit_code = ExitCode.RATE_LIMIT


class ComplexityBudgetError(RetryableError):
    """Complexity budget drained; honor `retry_in_seconds`."""

    exit_code = ExitCode.RATE_LIMIT


class ComplexityTooLargeError(MondoError):
    """Single-query complexity exceeded 5M — not retryable, shrink the query."""

    exit_code = ExitCode.VALIDATION


class ConcurrencyError(RetryableError):
    """`maxConcurrencyExceeded` — short jittered backoff."""

    exit_code = ExitCode.RATE_LIMIT


class IPRateLimitError(RetryableError):
    """IP-wide rate limit — long backoff."""

    exit_code = ExitCode.RATE_LIMIT


class ServiceError(RetryableError):
    """5xx, API_TEMPORARILY_BLOCKED, resource-locked — transient."""

    exit_code = ExitCode.NETWORK


class NetworkError(MondoError):
    """Transport-layer failure (DNS, connection refused, TLS). Usually retryable
    at the transport layer, but surfaced here after retries are exhausted."""

    exit_code = ExitCode.NETWORK


class CursorExpiredError(MondoError):
    """Cursor lifetime exceeded (60 min). Not retryable — re-issue the initial page."""

    exit_code = ExitCode.GENERIC


class WaitTimeoutError(MondoError):
    """Client-side wait timed out (e.g. `board duplicate --wait --timeout N`)."""

    exit_code = ExitCode.TIMEOUT


# Monday error code (from extensions.code) → exception class.
# Every code listed in monday-api.md §6 and plan.md §8.4 has an entry.
_CODE_MAP: dict[str, type[MondoError]] = {
    "ComplexityException": ComplexityTooLargeError,
    "COMPLEXITY_BUDGET_EXHAUSTED": ComplexityBudgetError,
    "Rate Limit Exceeded": RateLimitError,
    "RATE_LIMIT_EXCEEDED": RateLimitError,
    "maxConcurrencyExceeded": ConcurrencyError,
    "IP_RATE_LIMIT_EXCEEDED": IPRateLimitError,
    "UserUnauthorizedException": AuthError,
    "USER_UNAUTHORIZED": AuthError,
    "USER_ACCESS_DENIED": AuthError,
    "Unauthorized": AuthError,
    "missingRequiredPermissions": AuthError,
    "ResourceNotFoundException": NotFoundError,
    "ColumnValueException": ColumnValueError,
    "CorrectedValueException": ColumnValueError,
    "InvalidArgumentException": UsageError,
    "InvalidColumnIdException": UsageError,
    "InvalidUserIdException": UsageError,
    "InvalidBoardIdException": UsageError,
    "InvalidVersionException": UsageError,
    "ItemNameTooLongException": ValidationError,
    "ItemsLimitationException": ValidationError,
    "RecordInvalidException": ValidationError,
    "DeleteLastGroupException": UsageError,
    "JsonParseException": UsageError,
    "API_TEMPORARILY_BLOCKED": ServiceError,
    "CursorExpiredError": CursorExpiredError,
    "CursorException": CursorExpiredError,
}

# Fallback pattern matches when extensions.code is absent (legacy responses).
# Checked in order; first substring match wins.
_MESSAGE_FALLBACKS: tuple[tuple[str, type[MondoError]], ...] = (
    ("Rate Limit Exceeded", RateLimitError),
    ("Complexity budget", ComplexityBudgetError),
    ("Max concurrent", ConcurrencyError),
    ("IP rate limit", IPRateLimitError),
    ("Resource is currently locked", ServiceError),
    ("Unauthorized", AuthError),
)


def from_graphql_error(err: dict[str, Any]) -> MondoError:
    """Convert one entry from a GraphQL `errors` array into a typed exception."""
    extensions = err.get("extensions") or {}
    code = extensions.get("code")
    message = err.get("message") or "unknown GraphQL error"
    request_id = extensions.get("request_id")
    retry_in = extensions.get("retry_in_seconds")

    exc_class: type[MondoError] | None = _CODE_MAP.get(code) if code else None
    if exc_class is None:
        for needle, candidate in _MESSAGE_FALLBACKS:
            if needle in message:
                exc_class = candidate
                break
    if exc_class is None:
        exc_class = MondoError

    return exc_class(
        message,
        request_id=request_id,
        retry_in_seconds=retry_in,
        code=code,
    )


def from_response(response: dict[str, Any]) -> MondoError | None:
    """Return an exception for the first error in a GraphQL response, or None."""
    errs = response.get("errors")
    if not errs:
        return None
    return from_graphql_error(errs[0])
