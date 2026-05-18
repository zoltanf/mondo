"""--poll-until on item list / item get / board get re-fetches until the
JMESPath expression evaluates truthy, then emits the final payload.
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


def _item_response(state: str) -> dict:
    return {
        "data": {"items": [{
            "id": "987",
            "name": "Probe",
            "state": state,
            "url": "https://example.monday.com/boards/1/pulses/987",
            "group": {"id": "g1", "title": "T"},
            "column_values": [],
        }]},
        "extensions": {"request_id": "r"},
    }


def test_item_get_poll_until_short_circuits_when_already_truthy(httpx_mock: HTTPXMock) -> None:
    """If the predicate is already true on the first fetch, return immediately."""
    httpx_mock.add_response(url=ENDPOINT, method="POST", json=_item_response("active"))
    result = runner.invoke(
        app,
        ["-o", "json", "item", "get", "--id", "987",
         "--poll-until", "state == 'active'",
         "--poll-interval", "100ms",
         "--poll-timeout", "5s"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["state"] == "active"
    assert len(httpx_mock.get_requests()) == 1


def test_item_get_poll_until_polls_until_truthy(httpx_mock: HTTPXMock) -> None:
    """Sequence: inactive, inactive, active → returns after 3 polls."""
    for state in ("inactive", "inactive", "active"):
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_item_response(state))
    result = runner.invoke(
        app,
        ["-o", "json", "item", "get", "--id", "987",
         "--poll-until", "state == 'active'",
         "--poll-interval", "0s",
         "--poll-timeout", "10s"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["state"] == "active"
    assert len(httpx_mock.get_requests()) == 3


def test_item_get_poll_until_timeout_exits_nonzero(httpx_mock: HTTPXMock) -> None:
    """If the predicate never becomes truthy within the deadline, exit non-zero."""
    # Provide many responses (the helper will exhaust the timeout before
    # all are consumed); use is_optional to satisfy the unused-response check.
    for _ in range(20):
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_item_response("inactive"),
            is_optional=True,
        )
    result = runner.invoke(
        app,
        ["-o", "json", "item", "get", "--id", "987",
         "--poll-until", "state == 'active'",
         "--poll-interval", "0s",
         "--poll-timeout", "0s"],  # immediate timeout
    )
    assert result.exit_code != 0, result.output


def test_item_get_without_poll_runs_once(httpx_mock: HTTPXMock) -> None:
    """No --poll-until: behaviour is unchanged, one fetch only."""
    httpx_mock.add_response(url=ENDPOINT, method="POST", json=_item_response("active"))
    result = runner.invoke(app, ["-o", "json", "item", "get", "--id", "987"])
    assert result.exit_code == 0, result.output
    assert len(httpx_mock.get_requests()) == 1


def test_item_list_poll_until_waits_for_n_items(httpx_mock: HTTPXMock) -> None:
    """item list --poll-until 'length(@) >= `2`' waits for at least 2 items."""
    httpx_mock.add_response(
        url=ENDPOINT, method="POST",
        json={
            "data": {"boards": [{"items_page": {"cursor": None, "items": [
                {"id": "1", "name": "A", "state": "active",
                 "group": {"id": "g1", "title": "T"}, "column_values": []},
            ]}}]},
            "extensions": {"request_id": "r"},
        },
    )
    httpx_mock.add_response(
        url=ENDPOINT, method="POST",
        json={
            "data": {"boards": [{"items_page": {"cursor": None, "items": [
                {"id": "1", "name": "A", "state": "active",
                 "group": {"id": "g1", "title": "T"}, "column_values": []},
                {"id": "2", "name": "B", "state": "active",
                 "group": {"id": "g1", "title": "T"}, "column_values": []},
            ]}}]},
            "extensions": {"request_id": "r"},
        },
    )
    result = runner.invoke(
        app,
        ["-o", "json", "item", "list", "--board", "42",
         "--poll-until", "length(@) >= `2`",
         "--poll-interval", "0s",
         "--poll-timeout", "10s"],
    )
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert len(rows) == 2


def test_invalid_poll_interval_errors(httpx_mock: HTTPXMock) -> None:
    """A bad --poll-interval value should error usage-style (exit 2)."""
    httpx_mock.add_response(
        url=ENDPOINT, method="POST", json=_item_response("active"), is_optional=True,
    )
    result = runner.invoke(
        app,
        ["item", "get", "--id", "987",
         "--poll-until", "state == 'active'",
         "--poll-interval", "forever"],
    )
    assert result.exit_code == 2, result.output
