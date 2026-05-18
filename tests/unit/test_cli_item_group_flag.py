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
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {"boards": [{"items_page": {"cursor": None, "items": []}}]},
            "extensions": {"request_id": "r"},
        },
        is_optional=True,
    )
    result = runner.invoke(
        app, ["item", "list", "--board", "42", "--group", "topics"]
    )
    combined = (result.output or "") + (result.stderr or "")
    assert "No such option" not in combined, combined


def test_group_flag_produces_same_query_as_filter(httpx_mock: HTTPXMock) -> None:
    """`--group topics` should send the same GraphQL query_params as
    `--filter group=topics`."""
    _stub_items_page(httpx_mock, [])
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
    assert len(requests) == 2
    body1 = json.loads(requests[0].content)
    body2 = json.loads(requests[1].content)
    assert body1["variables"] == body2["variables"], (
        f"--group vs --filter sent different variables:\n"
        f"  --group: {body1['variables']!r}\n"
        f"  --filter: {body2['variables']!r}"
    )


def test_group_flag_combines_with_filter(httpx_mock: HTTPXMock) -> None:
    """`--group topics --filter status=Done` should send TWO rules:
    {column_id: group, ...} AND {column_id: status, ...}."""
    _stub_items_page(httpx_mock, [])
    result = runner.invoke(
        app,
        ["-o", "json", "item", "list", "--board", "42",
         "--group", "topics", "--filter", "status=Done"],
    )
    assert result.exit_code == 0, result.output
    request = httpx_mock.get_requests()[0]
    body = json.loads(request.content)
    qp = body["variables"].get("qp") or {}
    rules = qp.get("rules") or []
    column_ids = {r["column_id"] for r in rules}
    assert column_ids == {"group", "status"}, rules
