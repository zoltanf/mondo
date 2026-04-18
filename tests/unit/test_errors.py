"""Tests for mondo.api.errors — exception hierarchy, error code mapping, exit codes."""

from __future__ import annotations

import pytest

from mondo.api import errors


class TestExitCodes:
    """The plan §5.4 specifies exit codes that MUST be stable."""

    def test_canonical_exit_codes(self) -> None:
        assert errors.ExitCode.SUCCESS == 0
        assert errors.ExitCode.GENERIC == 1
        assert errors.ExitCode.USAGE == 2
        assert errors.ExitCode.AUTH == 3
        assert errors.ExitCode.RATE_LIMIT == 4
        assert errors.ExitCode.VALIDATION == 5
        assert errors.ExitCode.NOT_FOUND == 6
        assert errors.ExitCode.NETWORK == 7


class TestExceptionHierarchy:
    def test_mondo_error_is_base(self) -> None:
        assert issubclass(errors.AuthError, errors.MondoError)
        assert issubclass(errors.NotFoundError, errors.MondoError)
        assert issubclass(errors.RateLimitError, errors.MondoError)

    def test_retryable_errors_share_base(self) -> None:
        assert issubclass(errors.RateLimitError, errors.RetryableError)
        assert issubclass(errors.ComplexityBudgetError, errors.RetryableError)
        assert issubclass(errors.ConcurrencyError, errors.RetryableError)
        assert issubclass(errors.IPRateLimitError, errors.RetryableError)
        assert issubclass(errors.ServiceError, errors.RetryableError)

    def test_non_retryable_are_not_retryable(self) -> None:
        assert not issubclass(errors.AuthError, errors.RetryableError)
        assert not issubclass(errors.NotFoundError, errors.RetryableError)
        assert not issubclass(errors.ColumnValueError, errors.RetryableError)
        assert not issubclass(errors.UsageError, errors.RetryableError)

    def test_exception_carries_request_id(self) -> None:
        exc = errors.AuthError("not allowed", request_id="abc-123")
        assert exc.request_id == "abc-123"
        assert "abc-123" in str(exc)

    def test_exception_without_request_id(self) -> None:
        exc = errors.AuthError("not allowed")
        assert exc.request_id is None
        assert "abc-123" not in str(exc)

    def test_exception_exit_code_class_attribute(self) -> None:
        assert errors.AuthError.exit_code == errors.ExitCode.AUTH
        assert errors.NotFoundError.exit_code == errors.ExitCode.NOT_FOUND
        assert errors.ColumnValueError.exit_code == errors.ExitCode.VALIDATION
        assert errors.UsageError.exit_code == errors.ExitCode.USAGE
        assert errors.RateLimitError.exit_code == errors.ExitCode.RATE_LIMIT


class TestFromGraphQLError:
    """Test the `from_graphql_error` dispatch based on extensions.code."""

    def _err(self, code: str, message: str = "boom", request_id: str = "r-1") -> dict:
        return {
            "message": message,
            "extensions": {"code": code, "request_id": request_id},
        }

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("ComplexityException", "ComplexityTooLargeError"),
            ("COMPLEXITY_BUDGET_EXHAUSTED", "ComplexityBudgetError"),
            ("Rate Limit Exceeded", "RateLimitError"),
            ("RATE_LIMIT_EXCEEDED", "RateLimitError"),
            ("maxConcurrencyExceeded", "ConcurrencyError"),
            ("IP_RATE_LIMIT_EXCEEDED", "IPRateLimitError"),
            ("UserUnauthorizedException", "AuthError"),
            ("USER_UNAUTHORIZED", "AuthError"),
            ("USER_ACCESS_DENIED", "AuthError"),
            ("Unauthorized", "AuthError"),
            ("missingRequiredPermissions", "AuthError"),
            ("ResourceNotFoundException", "NotFoundError"),
            ("ColumnValueException", "ColumnValueError"),
            ("CorrectedValueException", "ColumnValueError"),
            ("InvalidArgumentException", "UsageError"),
            ("InvalidColumnIdException", "UsageError"),
            ("InvalidUserIdException", "UsageError"),
            ("InvalidBoardIdException", "UsageError"),
            ("InvalidVersionException", "UsageError"),
            ("ItemNameTooLongException", "ValidationError"),
            ("ItemsLimitationException", "ValidationError"),
            ("RecordInvalidException", "ValidationError"),
            ("DeleteLastGroupException", "UsageError"),
            ("JsonParseException", "UsageError"),
            ("API_TEMPORARILY_BLOCKED", "ServiceError"),
            ("CursorExpiredError", "CursorExpiredError"),
        ],
    )
    def test_maps_known_code_to_class(self, code: str, expected: str) -> None:
        exc = errors.from_graphql_error(self._err(code))
        assert type(exc).__name__ == expected
        assert exc.request_id == "r-1"

    def test_unknown_code_defaults_to_mondo_error(self) -> None:
        exc = errors.from_graphql_error(self._err("SomeBrandNewThing"))
        assert isinstance(exc, errors.MondoError)
        # Bare MondoError, not one of the subclasses
        assert type(exc) is errors.MondoError

    def test_fuzzy_match_on_message_when_code_missing(self) -> None:
        # Legacy errors may have no extensions.code — fall back to message matching
        err = {"message": "Rate Limit Exceeded", "extensions": {}}
        exc = errors.from_graphql_error(err)
        assert isinstance(exc, errors.RateLimitError)

    def test_locked_message_maps_to_service_error(self) -> None:
        err = {"message": "Resource is currently locked", "extensions": {}}
        exc = errors.from_graphql_error(err)
        assert isinstance(exc, errors.ServiceError)

    def test_retry_in_seconds_extracted(self) -> None:
        err = {
            "message": "Complexity budget exhausted",
            "extensions": {"code": "COMPLEXITY_BUDGET_EXHAUSTED", "retry_in_seconds": 42},
        }
        exc = errors.from_graphql_error(err)
        assert isinstance(exc, errors.ComplexityBudgetError)
        assert exc.retry_in_seconds == 42


class TestFromResponse:
    """from_response: pick the first error out of a full GraphQL response envelope."""

    def test_returns_none_when_no_errors(self) -> None:
        assert errors.from_response({"data": {"me": {"id": 1}}}) is None

    def test_returns_exception_when_errors_present(self) -> None:
        resp = {
            "data": None,
            "errors": [
                {
                    "message": "Not found",
                    "extensions": {"code": "ResourceNotFoundException", "request_id": "x"},
                }
            ],
        }
        exc = errors.from_response(resp)
        assert isinstance(exc, errors.NotFoundError)
        assert exc.request_id == "x"
