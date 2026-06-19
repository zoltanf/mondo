"""--filter <col>=<label> against a status/dropdown column emits a clear,
actionable error when the label doesn't exist.

Friction report C3: agents wrote `--filter status=High` against boards
where the actual labels are `[Done, Working on it, Stuck]`, and got
either silent 0-row responses or a terse error. We now error fast with
the known labels and a pointer to `mondo column labels --board X --column
status` so the agent can recover in one step.
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


def _stub_columns(httpx_mock: HTTPXMock) -> None:
    """Stub the board-columns fetch that --filter triggers."""
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {
                "boards": [
                    {
                        "id": "42",
                        "columns": [
                            {
                                "id": "status",
                                "title": "Status",
                                "type": "status",
                                "settings_str": json.dumps(
                                    {"labels": {"0": "Done", "1": "Working on it", "2": "Stuck"}}
                                ),
                                "archived": False,
                            },
                        ],
                    }
                ]
            },
            "extensions": {"request_id": "r"},
        },
        is_optional=True,
    )
    # An items_page response in case the filter is accepted and the path
    # progresses to fetching items (no-op since the test expects an error).
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json={
            "data": {"boards": [{"items_page": {"cursor": None, "items": []}}]},
            "extensions": {"request_id": "r"},
        },
        is_optional=True,
    )


def test_unknown_status_label_lists_known_labels(httpx_mock: HTTPXMock) -> None:
    _stub_columns(httpx_mock)
    result = runner.invoke(
        app,
        ["item", "list", "--board", "42", "--filter", "status=NotALabel"],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (result.stderr or "")
    # Existing codec contributes "Known: Done, Working on it, Stuck"
    assert "Done" in combined
    assert "Working on it" in combined
    assert "Stuck" in combined


def test_unknown_status_label_points_to_mondo_column_labels(httpx_mock: HTTPXMock) -> None:
    """The error should tell the agent how to discover labels on its own."""
    _stub_columns(httpx_mock)
    result = runner.invoke(
        app,
        ["item", "list", "--board", "42", "--filter", "status=NotALabel"],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (result.stderr or "")
    assert "mondo column labels" in combined, (
        f"expected pointer to `mondo column labels` in error; got: {combined!r}"
    )
    # Includes the board_id and column_id so it's copy-pasteable
    assert "--board 42" in combined or "42" in combined
    assert "--column status" in combined or "status" in combined


def test_unknown_status_label_uses_exit_2_not_6(httpx_mock: HTTPXMock) -> None:
    """Usage errors must use exit 2 (the codec used to surface ValueError
    via Click which uses exit 2; lock that in)."""
    _stub_columns(httpx_mock)
    result = runner.invoke(
        app,
        ["item", "list", "--board", "42", "--filter", "status=NotALabel"],
    )
    assert result.exit_code == 2, (result.exit_code, result.output)
