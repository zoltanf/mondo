"""`mondo item list --parent <id>` returns the subitems of that parent.

Friction report B2: agents want a single mental model — `item list` is
how you list items, regardless of whether they're top-level or subitems.
Currently you have to switch to `mondo subitem list --parent <id>`. We
fold the subitem-listing path into `item list` so `--parent` is just
another scope filter.

The implementation delegates to the same SUBITEMS_LIST query subitem list
uses, so the returned shape is identical.
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
    # Isolate the cache dir so a sibling test's warm `subitems/111.json`
    # doesn't short-circuit the second invocation in the same-query check.
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))


def _stub_subitems(httpx_mock: HTTPXMock, subitems: list[dict]) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {
                "items": [
                    {
                        "id": "111",
                        "name": "Parent",
                        "board": {"id": "42", "name": "B"},
                        "subitems": subitems,
                    }
                ]
            },
            "extensions": {"request_id": "r"},
        },
    )


def test_parent_flag_returns_subitems(httpx_mock: HTTPXMock) -> None:
    _stub_subitems(
        httpx_mock,
        [
            {
                "id": "201",
                "name": "Sub A",
                "state": "active",
                "board": {"id": "777"},
                "column_values": [],
            },
            {
                "id": "202",
                "name": "Sub B",
                "state": "active",
                "board": {"id": "777"},
                "column_values": [],
            },
        ],
    )
    result = runner.invoke(
        app,
        ["-o", "json", "item", "list", "--parent", "111"],
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert {r["id"] for r in rows} == {"201", "202"}


def test_parent_flag_makes_board_optional(httpx_mock: HTTPXMock) -> None:
    """When --parent is set, --board / positional BOARD_ID is not required."""
    _stub_subitems(httpx_mock, [])
    result = runner.invoke(app, ["item", "list", "--parent", "111"])
    combined = (result.output or "") + (result.stderr or "")
    assert "missing board ID" not in combined, combined
    assert "No such option" not in combined, combined


def test_parent_flag_uses_same_query_as_subitem_list(httpx_mock: HTTPXMock) -> None:
    """item list --parent X should send the same SUBITEMS_LIST query that
    subitem list --parent X sends."""
    _stub_subitems(httpx_mock, [])
    _stub_subitems(httpx_mock, [])
    r1 = runner.invoke(app, ["-o", "json", "item", "list", "--parent", "111"])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(app, ["-o", "json", "subitem", "list", "--parent", "111"])
    assert r2.exit_code == 0, r2.output

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    body1 = json.loads(requests[0].content)
    body2 = json.loads(requests[1].content)
    assert body1["query"] == body2["query"], (
        "item list --parent and subitem list --parent sent different GraphQL queries"
    )
    assert body1["variables"] == body2["variables"]
