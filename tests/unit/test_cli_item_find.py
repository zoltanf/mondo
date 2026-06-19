"""`mondo item find --board X --column COL --value VAL` finds items by
column value.

Friction report B4: agents writing GraphQL because there's no
`item find`. We provide it as sugar over `item list --filter COL=VAL`,
so it behaves the same w.r.t. codec dispatch + the new
mondo-column-labels pointer on errors.
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
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")


def _stub_status_column(httpx_mock: HTTPXMock) -> None:
    """First request — board columns; needed because find uses --filter codec dispatch."""
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


def _stub_items(httpx_mock: HTTPXMock, items: list[dict]) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {"boards": [{"items_page": {"cursor": None, "items": items}}]},
            "extensions": {"request_id": "r"},
        },
    )


def test_item_find_returns_matching_items(httpx_mock: HTTPXMock) -> None:
    _stub_status_column(httpx_mock)
    _stub_items(httpx_mock, [
        {"id": "1", "name": "Alpha", "state": "active",
         "group": {"id": "g1", "title": "T"}, "column_values": []},
        {"id": "2", "name": "Beta", "state": "active",
         "group": {"id": "g1", "title": "T"}, "column_values": []},
    ])
    result = runner.invoke(
        app,
        ["-o", "json", "item", "find",
         "--board", "42", "--column", "status", "--value", "Done"],
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert {r["id"] for r in rows} == {"1", "2"}


def test_item_find_sends_same_query_as_filter(httpx_mock: HTTPXMock) -> None:
    """item find COL VAL must send the same items_page query as
    item list --filter COL=VAL (both use the codec for status indices)."""
    _stub_status_column(httpx_mock)
    _stub_items(httpx_mock, [])
    _stub_status_column(httpx_mock)
    _stub_items(httpx_mock, [])

    r1 = runner.invoke(
        app,
        ["-o", "json", "item", "find",
         "--board", "42", "--column", "status", "--value", "Done"],
    )
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(
        app,
        ["-o", "json", "item", "list",
         "--board", "42", "--filter", "status=Done"],
    )
    assert r2.exit_code == 0, r2.output

    requests = httpx_mock.get_requests()
    # Two invocations x (columns fetch + items_page) = 4 requests
    # The 2nd and 4th are the items_page calls.
    items_bodies = [json.loads(r.content) for r in requests[1::2]]
    assert items_bodies[0]["variables"] == items_bodies[1]["variables"], (
        f"item find and item list --filter sent different items queries:\n"
        f"  find: {items_bodies[0]['variables']!r}\n"
        f"  list: {items_bodies[1]['variables']!r}"
    )


def test_item_find_unknown_label_errors_with_pointer(httpx_mock: HTTPXMock) -> None:
    """When --value doesn't match a known status label, find should error
    with the same recovery pointer item list emits."""
    _stub_status_column(httpx_mock)
    result = runner.invoke(
        app,
        ["item", "find", "--board", "42",
         "--column", "status", "--value", "NotALabel"],
    )
    assert result.exit_code == 2, result.output
    combined = (result.output or "") + (result.stderr or "")
    assert "Done" in combined
    assert "mondo column labels" in combined


def test_item_find_in_help_index() -> None:
    """`mondo item --help` should list 'find' alongside list/get/create."""
    result = runner.invoke(app, ["item", "--help"])
    assert result.exit_code == 0
    assert "find" in result.output


def test_item_find_has_examples():
    """Lint dependency: every read leaf needs at least one -q example."""
    from mondo.cli._examples import EXAMPLES
    exs = EXAMPLES.get("item find") or []
    assert exs, "item find needs Examples (read-leaf lint)"
    assert any("-q " in ex.command for ex in exs), (
        "item find needs at least one -q example (read-leaf lint)"
    )
