"""Tests for mondo.api.client — MondayClient."""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from mondo.api.client import MondayClient
from mondo.api.errors import (
    AuthError,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServiceError,
)
from mondo.version import __version__

ENDPOINT = "https://api.monday.com/v2"


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "req-1"}}


class TestHeaders:
    def test_authorization_without_bearer_prefix(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"me": {"id": 1}}))
        client = MondayClient(token="my-secret-token", api_version="2026-01")
        client.execute("query { me { id } }")
        req = httpx_mock.get_request()
        assert req is not None
        assert req.headers["Authorization"] == "my-secret-token"
        assert "Bearer" not in req.headers["Authorization"]

    def test_api_version_header(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({}))
        client = MondayClient(token="t", api_version="2026-04")
        client.execute("query { __typename }")
        assert httpx_mock.get_request().headers["API-Version"] == "2026-04"  # type: ignore[union-attr]

    def test_user_agent_includes_version(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({}))
        client = MondayClient(token="t", api_version="2026-01")
        client.execute("query { __typename }")
        ua = httpx_mock.get_request().headers["User-Agent"]  # type: ignore[union-attr]
        assert ua == f"mondo/{__version__}"

    def test_content_type_is_json(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({}))
        client = MondayClient(token="t", api_version="2026-01")
        client.execute("query { __typename }")
        assert httpx_mock.get_request().headers["Content-Type"] == "application/json"  # type: ignore[union-attr]


class TestExecuteBody:
    def test_posts_query_and_variables(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({}))
        # inject_complexity=False keeps the exact query bytes — otherwise the
        # client rewrites outgoing queries to carry the `complexity` meter.
        client = MondayClient(token="t", api_version="2026-01", inject_complexity=False)
        client.execute("query ($id: ID!) { me { id } }", variables={"id": 1})
        import json as _json

        body = _json.loads(httpx_mock.get_request().content)  # type: ignore[union-attr]
        assert body["query"] == "query ($id: ID!) { me { id } }"
        assert body["variables"] == {"id": 1}

    def test_no_variables_sends_empty_dict(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({}))
        client = MondayClient(token="t", api_version="2026-01")
        client.execute("query { __typename }")
        import json as _json

        body = _json.loads(httpx_mock.get_request().content)  # type: ignore[union-attr]
        assert body["variables"] == {}

    def test_returns_full_envelope(self, httpx_mock: HTTPXMock) -> None:
        payload = {
            "data": {"me": {"id": "1", "name": "Alice"}},
            "extensions": {"request_id": "abc"},
        }
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=payload)
        client = MondayClient(token="t", api_version="2026-01")
        result = client.execute("query { me { id name } }")
        assert result == payload


class TestErrorMapping:
    def test_graphql_auth_error_raises_auth_error(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "errors": [
                    {
                        "message": "you lack permissions",
                        "extensions": {
                            "code": "UserUnauthorizedException",
                            "request_id": "r-1",
                        },
                    }
                ]
            },
        )
        client = MondayClient(token="t", api_version="2026-01")
        with pytest.raises(AuthError) as exc_info:
            client.execute("query { me { id } }")
        assert exc_info.value.request_id == "r-1"

    def test_not_found_raises_not_found_error(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "errors": [
                    {
                        "message": "item not found",
                        "extensions": {"code": "ResourceNotFoundException"},
                    }
                ]
            },
        )
        client = MondayClient(token="t", api_version="2026-01", max_retries=1)
        with pytest.raises(NotFoundError):
            client.execute("query { items(ids:[1]) { id } }")

    def test_http_401_raises_auth_error(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            status_code=401,
            text="Unauthorized",
        )
        client = MondayClient(token="t", api_version="2026-01")
        with pytest.raises(AuthError):
            client.execute("query { me { id } }")

    def test_http_404_raises_not_found(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            status_code=404,
            text="Not Found",
        )
        client = MondayClient(token="t", api_version="2026-01", max_retries=1)
        with pytest.raises(NotFoundError):
            client.execute("query { me { id } }")

    def test_http_500_raises_service_error(self, httpx_mock: HTTPXMock) -> None:
        # All 3 retry attempts return 500 → ServiceError after exhaustion
        for _ in range(3):
            httpx_mock.add_response(url=ENDPOINT, method="POST", status_code=500, text="boom")
        client = MondayClient(token="t", api_version="2026-01", max_retries=3)
        with pytest.raises(ServiceError):
            client.execute("query { me { id } }")


class TestRetry:
    def test_retries_on_rate_limit_then_succeeds(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "errors": [
                    {
                        "message": "Rate Limit Exceeded",
                        "extensions": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "retry_in_seconds": 0,
                        },
                    }
                ]
            },
        )
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"me": {"id": "1"}}))
        client = MondayClient(
            token="t",
            api_version="2026-01",
            max_retries=3,
            retry_sleep=lambda _s: None,  # instant retry in tests
        )
        result = client.execute("query { me { id } }")
        assert result["data"]["me"]["id"] == "1"
        assert len(httpx_mock.get_requests()) == 2

    def test_gives_up_after_max_retries(self, httpx_mock: HTTPXMock) -> None:
        for _ in range(3):
            httpx_mock.add_response(
                url=ENDPOINT,
                method="POST",
                json={
                    "errors": [
                        {
                            "message": "Rate Limit Exceeded",
                            "extensions": {
                                "code": "RATE_LIMIT_EXCEEDED",
                                "retry_in_seconds": 0,
                            },
                        }
                    ]
                },
            )
        client = MondayClient(
            token="t",
            api_version="2026-01",
            max_retries=3,
            retry_sleep=lambda _s: None,
        )
        with pytest.raises(RateLimitError):
            client.execute("query { me { id } }")

    def test_does_not_retry_on_auth_error(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "errors": [
                    {
                        "message": "nope",
                        "extensions": {"code": "UserUnauthorizedException"},
                    }
                ]
            },
        )
        client = MondayClient(
            token="t",
            api_version="2026-01",
            max_retries=5,
            retry_sleep=lambda _s: None,
        )
        with pytest.raises(AuthError):
            client.execute("query { me { id } }")
        assert len(httpx_mock.get_requests()) == 1  # single try, no retries

    def test_retries_on_complexity_budget(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "errors": [
                    {
                        "message": "Complexity budget exhausted",
                        "extensions": {
                            "code": "COMPLEXITY_BUDGET_EXHAUSTED",
                            "retry_in_seconds": 0,
                        },
                    }
                ]
            },
        )
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"me": {"id": "1"}}))
        client = MondayClient(
            token="t",
            api_version="2026-01",
            max_retries=3,
            retry_sleep=lambda _s: None,
        )
        result = client.execute("query { me { id } }")
        assert result["data"]["me"]["id"] == "1"


class TestNetworkErrors:
    def test_connection_error_wrapped(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_exception(httpx.ConnectError("no route"))
        httpx_mock.add_exception(httpx.ConnectError("no route"))
        client = MondayClient(
            token="t",
            api_version="2026-01",
            max_retries=2,
            retry_sleep=lambda _s: None,
        )
        with pytest.raises(NetworkError):
            client.execute("query { me { id } }")

    def test_timeout_wrapped(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_exception(httpx.ReadTimeout("slow"))
        httpx_mock.add_exception(httpx.ReadTimeout("slow"))
        client = MondayClient(
            token="t",
            api_version="2026-01",
            max_retries=2,
            retry_sleep=lambda _s: None,
        )
        with pytest.raises(NetworkError):
            client.execute("query { me { id } }")


class TestRegistersSecret:
    """The client should register the token with the redaction logger."""

    def test_token_registered_for_redaction(self) -> None:
        from mondo.logging_ import redact

        _ = MondayClient(token="unique-test-token-12345", api_version="2026-01")
        assert "unique-test-token-12345" not in redact(
            "header: Authorization: unique-test-token-12345"
        )
