"""`mondo item list --group <id>` is a first-class alias for
`--filter group=<id>`.

Friction report B1: the filter system already accepts `group=<id>` as a
special column-id (server-side), but `--filter` is undiscoverable. Agents
reach for `--group` and get "No such option". This test locks in the
alias and asserts the two forms produce identical GraphQL requests.
"""
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
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    # Isolate the cache to this test's tmpdir and disable it, so the
    # column-defs preflight that `--filter` (and `--group`, which desugars
    # into `--filter group=…`) triggers always hits a mocked GraphQL call
    # rather than a stale `~/.cache/mondo/` from a prior test run.
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")


def _stub_columns(httpx_mock: HTTPXMock) -> None:
    """Mock the COLUMNS_ON_BOARD preflight that --filter codec dispatch fires."""
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {"boards": [{
                "id": "42",
                "columns": [{
                    "id": "status",
                    "title": "Status",
                    "type": "status",
                    "settings_str": json.dumps({
                        "labels": {"0": "Done", "1": "Working on it", "2": "Stuck"}
                    }),
                    "archived": False,
                }],
            }]},
            "extensions": {"request_id": "r"},
        },
    )


def _stub_items_page(httpx_mock: HTTPXMock, items: list[dict]) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {"boards": [{"items_page": {"cursor": None, "items": items}}]},
            "extensions": {"request_id": "r"},
        },
    )


def test_group_flag_is_accepted(httpx_mock: HTTPXMock) -> None:
    """--group should parse without 'No such option'."""
    _stub_columns(httpx_mock)
    _stub_items_page(httpx_mock, [])
    result = runner.invoke(
        app, ["item", "list", "--board", "42", "--group", "topics"]
    )
    combined = (result.output or "") + (result.stderr or "")
    assert "No such option" not in combined, combined


def test_group_flag_produces_same_query_as_filter(httpx_mock: HTTPXMock) -> None:
    """`--group topics` should send the same GraphQL query_params as
    `--filter group=topics`."""
    _stub_columns(httpx_mock)
    _stub_items_page(httpx_mock, [])
    _stub_columns(httpx_mock)
    _stub_items_page(httpx_mock, [])

    r1 = runner.invoke(
        app, ["-o", "json", "item", "list", "--board", "42", "--group", "topics"]
    )
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(
        app, ["-o", "json", "item", "list", "--board", "42",
              "--filter", "group=topics"]
    )
    assert r2.exit_code == 0, r2.output

    requests = httpx_mock.get_requests()
    # Two invocations x (columns preflight + items_page) = 4 requests.
    # items_page bodies are the 2nd and 4th.
    items_bodies = [json.loads(r.content) for r in requests[1::2]]
    assert len(items_bodies) == 2
    assert items_bodies[0]["variables"] == items_bodies[1]["variables"], (
        f"--group vs --filter sent different variables:\n"
        f"  --group: {items_bodies[0]['variables']!r}\n"
        f"  --filter: {items_bodies[1]['variables']!r}"
    )


def test_group_flag_combines_with_filter(httpx_mock: HTTPXMock) -> None:
    """`--group topics --filter status=Done` should send TWO rules:
    {column_id: group, ...} AND {column_id: status, ...}."""
    _stub_columns(httpx_mock)
    _stub_items_page(httpx_mock, [])
    result = runner.invoke(
        app,
        ["-o", "json", "item", "list", "--board", "42",
         "--group", "topics", "--filter", "status=Done"],
    )
    assert result.exit_code == 0, result.output
    # The items_page request is the second POST (after the columns preflight).
    items_request = httpx_mock.get_requests()[1]
    body = json.loads(items_request.content)
    qp = body["variables"].get("qp") or {}
    rules = qp.get("rules") or []
    column_ids = {r["column_id"] for r in rules}
    assert column_ids == {"group", "status"}, rules
