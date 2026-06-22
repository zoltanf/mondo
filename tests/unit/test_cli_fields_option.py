"""End-to-end tests for the global --fields projection option.

`--fields id,name,...` runs before `-q '<jmespath>'`; both can be combined.
"""

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


def test_fields_trims_a_list_payload(httpx_mock: HTTPXMock) -> None:
    _graphql_ok(
        httpx_mock,
        {
            "users": [
                {"id": "1", "name": "Alice", "email": "a@x"},
                {"id": "2", "name": "Bob", "email": "b@x"},
            ]
        },
    )
    result = runner.invoke(
        app,
        [
            "--fields",
            "id,name",
            "-q",
            "users",
            "-o",
            "json",
            "graphql",
            "query { users { id name email } }",
        ],
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert rows == [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]


def test_fields_with_csv_output(httpx_mock: HTTPXMock) -> None:
    _graphql_ok(
        httpx_mock,
        {
            "users": [
                {"id": "1", "name": "Alice", "email": "a@x"},
            ]
        },
    )
    result = runner.invoke(
        app,
        [
            "--fields",
            "id,name",
            "-q",
            "users",
            "-o",
            "csv",
            "graphql",
            "query { users { id name email } }",
        ],
    )
    assert result.exit_code == 0, result.output
    rows = list(_csv.reader(io.StringIO(result.stdout)))
    assert rows[0] == ["id", "name"]
    assert rows[1] == ["1", "Alice"]


def test_fields_without_query_projects_dict(httpx_mock: HTTPXMock) -> None:
    """--fields without -q operates on the unwrapped `data` object that
    `mondo graphql` emits by default (the same payload -q would see)."""
    _graphql_ok(httpx_mock, {"me": {"id": "1", "name": "Alice", "email": "a@x"}})
    result = runner.invoke(
        app,
        ["--fields", "me", "-o", "json", "graphql", "query { me { id name email } }"],
    )
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)
    assert parsed == {"me": {"id": "1", "name": "Alice", "email": "a@x"}}


def test_fields_appears_in_help_as_global_option() -> None:
    """--fields lives in the global callback like -q/-o, so it appears
    on every command's help output."""
    result = runner.invoke(app, ["item", "list", "--help"])
    assert result.exit_code == 0
    # Either listed under Global options (root callback) or surfaced on the
    # command. For now we just verify it appears in the root --help.
    root_help = runner.invoke(app, ["--help"])
    assert root_help.exit_code == 0
    assert "--fields" in root_help.output


def test_query_runs_before_fields(httpx_mock: HTTPXMock) -> None:
    """Confirm pipeline order: -q first (extracts from envelope), then --fields
    (final row-shape projection)."""
    _graphql_ok(
        httpx_mock,
        {
            "users": [
                {"id": "1", "name": "Alice", "email": "a@x"},
                {"id": "2", "name": "Bob", "email": "b@x"},
            ]
        },
    )
    # Without --fields, -q 'users' returns the list.
    # With --fields id, each row is trimmed to {id}.
    result = runner.invoke(
        app,
        [
            "-q",
            "users",
            "--fields",
            "id",
            "-o",
            "json",
            "graphql",
            "query { users { id name email } }",
        ],
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert rows == [{"id": "1"}, {"id": "2"}]
