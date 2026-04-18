"""End-to-end CLI tests for `mondo graphql` using pytest-httpx."""

from __future__ import annotations

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
    """Isolate each test from the user's real config and env."""
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "test-token-12345-abcdef-long-enough")


def test_graphql_sends_query_and_prints_envelope(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={"data": {"me": {"id": "1", "name": "Alice"}}, "extensions": {"request_id": "r"}},
    )
    result = runner.invoke(app, ["graphql", "query { me { id name } }"])
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["data"]["me"]["name"] == "Alice"


def test_graphql_with_variables(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={"data": {"items": [{"id": "1"}]}, "extensions": {"request_id": "r"}},
    )
    result = runner.invoke(
        app,
        [
            "graphql",
            "query ($ids: [ID!]!) { items(ids:$ids) { id } }",
            "--vars",
            '{"ids":[1,2,3]}',
        ],
    )
    assert result.exit_code == 0, result.stdout
    req = httpx_mock.get_request()
    body = json.loads(req.content)  # type: ignore[union-attr]
    assert body["variables"] == {"ids": [1, 2, 3]}


def test_graphql_bad_variables_exits_2() -> None:
    result = runner.invoke(app, ["graphql", "query { me { id } }", "--vars", "not json"])
    assert result.exit_code == 2


def test_graphql_auth_error_exits_3(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        status_code=401,
        text="Unauthorized",
    )
    result = runner.invoke(app, ["graphql", "query { me { id } }"])
    assert result.exit_code == 3


def test_graphql_query_from_file(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    q = tmp_path / "q.graphql"
    q.write_text("query { me { id } }")
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={"data": {"me": {"id": "1"}}},
    )
    result = runner.invoke(app, ["graphql", f"@{q}"])
    assert result.exit_code == 0, result.stdout
    body = json.loads(httpx_mock.get_request().content)  # type: ignore[union-attr]
    assert body["query"] == "query { me { id } }"
