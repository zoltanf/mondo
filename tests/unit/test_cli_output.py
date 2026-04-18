"""End-to-end tests covering --output and --query on real commands."""

from __future__ import annotations

import csv as _csv
import io
import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")


def _graphql_ok(httpx_mock: HTTPXMock, data: dict) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={"data": data, "extensions": {"request_id": "r"}},
    )


# ------- graphql passthrough through formatter pipeline -------


class TestGraphqlFormats:
    def test_default_json(self, httpx_mock: HTTPXMock) -> None:
        _graphql_ok(httpx_mock, {"me": {"id": "1"}})
        result = runner.invoke(app, ["graphql", "query { me { id } }"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["data"]["me"]["id"] == "1"

    def test_output_yaml(self, httpx_mock: HTTPXMock) -> None:
        _graphql_ok(httpx_mock, {"me": {"id": "1"}})
        result = runner.invoke(app, ["-o", "yaml", "graphql", "query { me { id } }"])
        assert result.exit_code == 0
        assert "id: '1'" in result.stdout or 'id: "1"' in result.stdout or "id: 1" in result.stdout

    def test_query_extracts_nested_field(self, httpx_mock: HTTPXMock) -> None:
        _graphql_ok(httpx_mock, {"me": {"id": "42", "name": "Alice"}})
        result = runner.invoke(
            app,
            ["-q", "data.me.name", "-o", "none", "graphql", "query { me { id name } }"],
        )
        assert result.exit_code == 0
        assert result.stdout.strip() == "Alice"

    def test_query_with_csv_on_array_response(self, httpx_mock: HTTPXMock) -> None:
        _graphql_ok(
            httpx_mock,
            {
                "users": [
                    {"id": "1", "name": "Alice"},
                    {"id": "2", "name": "Bob"},
                ]
            },
        )
        result = runner.invoke(
            app,
            [
                "-q",
                "data.users",
                "-o",
                "csv",
                "graphql",
                "query { users { id name } }",
            ],
        )
        assert result.exit_code == 0
        rows = list(_csv.reader(io.StringIO(result.stdout)))
        assert rows[0] == ["id", "name"]
        assert rows[1] == ["1", "Alice"]
        assert rows[2] == ["2", "Bob"]

    def test_invalid_query_exits_usage_error(self, httpx_mock: HTTPXMock) -> None:
        _graphql_ok(httpx_mock, {"me": {"id": "1"}})
        result = runner.invoke(app, ["-q", "[", "graphql", "query { me { id } }"])
        # `[` → JMESPath lexer error → ValueError → exit code 1 (generic) via uncaught
        # Actually: apply_query raises ValueError; format_output never runs.
        # Typer wraps uncaught exceptions as exit code 1.
        assert result.exit_code != 0

    def test_unknown_output_format_exits_usage_error(self, httpx_mock: HTTPXMock) -> None:
        # Typer's Choice enforcement should catch this before the command runs.
        result = runner.invoke(app, ["-o", "bogus", "graphql", "query { me { id } }"])
        assert result.exit_code == 2
        assert len(httpx_mock.get_requests()) == 0


# ------- auth status formatters -------


def _me_response() -> dict:
    return {
        "data": {
            "me": {
                "id": "42",
                "name": "Alice",
                "email": "a@x.com",
                "is_admin": True,
                "account": {"id": "100", "name": "Acme", "slug": "acme", "tier": "pro"},
            }
        },
        "extensions": {"request_id": "r"},
    }


class TestAuthStatusFormats:
    def test_default_json(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_me_response())
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["user_name"] == "Alice"
        assert parsed["account_slug"] == "acme"
        assert parsed["token_source"] == "MONDAY_API_TOKEN environment variable"

    def test_query_projection_to_scalar(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_me_response())
        result = runner.invoke(app, ["-q", "account_name", "-o", "none", "auth", "status"])
        assert result.exit_code == 0
        assert result.stdout.strip() == "Acme"
