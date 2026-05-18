"""`mondo update get --id X` includes the replies thread by default.

Friction report B5: a handful of sessions fell back to raw GraphQL to
fetch `updates { replies { ... } }` because they didn't realise the
top-level get returned replies. This locks in default-on behavior so a
future query trim doesn't silently drop replies again.
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


def test_update_get_query_selects_replies() -> None:
    """The default UPDATE_GET query must include the `replies` selection.
    This is the contract: agents shouldn't have to remember a --with-replies
    flag."""
    from mondo.api.queries import UPDATE_GET
    assert "replies" in UPDATE_GET
    # Each reply must carry enough to be useful (id, body, creator).
    assert "replies { id body" in UPDATE_GET


def test_update_get_output_includes_replies_array(httpx_mock: HTTPXMock) -> None:
    """End-to-end: replies appear in the JSON output of `mondo update get`."""
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {"updates": [{
                "id": "555",
                "body": "<p>Top-level</p>",
                "text_body": "Top-level",
                "creator": {"id": "1", "name": "Alice"},
                "item_id": "999",
                "created_at": "2026-05-18T10:00:00Z",
                "updated_at": "2026-05-18T10:00:00Z",
                "replies": [
                    {"id": "556", "body": "First reply",
                     "creator": {"id": "2", "name": "Bob"},
                     "created_at": "2026-05-18T11:00:00Z"},
                    {"id": "557", "body": "Second reply",
                     "creator": {"id": "3", "name": "Carol"},
                     "created_at": "2026-05-18T12:00:00Z"},
                ],
                "assets": [],
                "likes": [],
                "pinned_to_top": [],
            }]},
            "extensions": {"request_id": "r"},
        },
    )
    result = runner.invoke(app, ["-o", "json", "update", "get", "--id", "555"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "replies" in payload
    assert len(payload["replies"]) == 2
    assert payload["replies"][0]["body"] == "First reply"


def test_update_get_query_replies_via_jmespath(httpx_mock: HTTPXMock) -> None:
    """Common usage: `mondo update get --id X -q replies` projects just
    the replies array.  Locks in -q compatibility with the replies field."""
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {"updates": [{
                "id": "555",
                "body": "p",
                "text_body": "p",
                "creator": {"id": "1", "name": "A"},
                "item_id": "999",
                "created_at": "2026-05-18T10:00:00Z",
                "updated_at": "2026-05-18T10:00:00Z",
                "replies": [
                    {"id": "556", "body": "r",
                     "creator": {"id": "2", "name": "B"},
                     "created_at": "2026-05-18T11:00:00Z"},
                ],
                "assets": [], "likes": [], "pinned_to_top": [],
            }]},
            "extensions": {"request_id": "r"},
        },
    )
    result = runner.invoke(
        app, ["-q", "replies", "-o", "json", "update", "get", "--id", "555"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert payload[0]["body"] == "r"


def test_update_get_help_mentions_replies() -> None:
    """Discoverability: help text should advertise that replies come back
    so agents stop falling back to GraphQL."""
    result = runner.invoke(app, ["update", "get", "--help"])
    assert result.exit_code == 0
    assert "replies" in result.output.lower(), (
        "update get --help should mention 'replies' so agents discover the "
        "behavior without reading the GraphQL fragment"
    )
