"""End-to-end CLI tests for `mondo import board ...`."""

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


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


COLS_RESPONSE = _ok(
    {
        "boards": [
            {
                "id": "42",
                "name": "B",
                "columns": [
                    {
                        "id": "status",
                        "title": "Status",
                        "type": "status",
                        "settings_str": "{}",
                        "archived": False,
                    },
                    {
                        "id": "date4",
                        "title": "Due",
                        "type": "date",
                        "settings_str": "{}",
                        "archived": False,
                    },
                ],
            }
        ]
    }
)


def _write_csv(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


class TestBasicImport:
    def test_two_rows(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "items.csv"
        _write_csv(
            src,
            [
                "name,Status,Due",
                "Alpha,Done,2026-04-25",
                "Beta,Working on it,",
            ],
        )
        # Preflight (columns) + two create_item mutations.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "2", "name": "Beta"}}),
        )
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["summary"]["created"] == 2
        assert parsed["summary"]["failed"] == 0
        # Check that the status codec picked "Done" (index 0/ label)
        second_body = json.loads(httpx_mock.get_requests()[1].content)
        values = json.loads(second_body["variables"]["values"])
        assert values["status"] == {"label": "Done"}
        assert values["date4"] == {"date": "2026-04-25"}

    def test_empty_name_fails_row(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        # Second column keeps the line non-blank so DictReader doesn't skip it.
        _write_csv(src, ["name,Status", ",Done"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 1, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["summary"]["failed"] == 1
        assert parsed["summary"]["created"] == 0

    def test_dry_run_no_mutation(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name", "Alpha", "Beta"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        result = runner.invoke(
            app,
            ["--dry-run", "import", "board", "--board", "42", "--from", str(src)],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["summary"]["created"] == 0
        assert all(r["status"] == "dry-run" for r in parsed["results"])
        # Only the preflight query should have been sent.
        assert len(httpx_mock.get_requests()) == 1


class TestMapping:
    def test_explicit_mapping(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(
            src,
            ["name,Stage,Due Date", "Alpha,Done,2026-04-25"],
        )
        mapping = tmp_path / "map.yaml"
        mapping.write_text(
            "columns:\n  Stage: status\n  Due Date: date4\n",
            encoding="utf-8",
        )
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(
            app,
            [
                "import",
                "board",
                "--board",
                "42",
                "--from",
                str(src),
                "--mapping",
                str(mapping),
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        values = json.loads(body["variables"]["values"])
        assert "status" in values and "date4" in values

    def test_unknown_header_ignored(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,Mystery,Status", "Alpha,foo,Done"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        values = json.loads(body["variables"]["values"])
        assert "Mystery" not in values
        assert "status" in values


class TestIdempotency:
    def test_skips_existing(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name", "Alpha", "Beta"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        # Pre-fetch of existing names (single page)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "items_page": {
                                "cursor": None,
                                "items": [
                                    {"id": "99", "name": "Alpha"},
                                ],
                            }
                        }
                    ]
                }
            ),
        )
        # Only Beta should be created
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "100", "name": "Beta"}}),
        )
        result = runner.invoke(
            app,
            [
                "import",
                "board",
                "--board",
                "42",
                "--from",
                str(src),
                "--idempotency-name",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["summary"] == {"created": 1, "skipped": 1, "failed": 0, "total": 2}
        skipped_row = next(r for r in parsed["results"] if r["status"] == "skipped")
        assert skipped_row["name"] == "Alpha"


class TestGroup:
    def test_default_group_applied(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name", "Alpha"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        result = runner.invoke(
            app,
            [
                "import",
                "board",
                "--board",
                "42",
                "--from",
                str(src),
                "--group",
                "topics",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[1].content)
        assert body["variables"]["group"] == "topics"

    def test_per_row_group_overrides_default(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        src = tmp_path / "i.csv"
        _write_csv(src, ["name,group", "Alpha,grp_a", "Beta,"])
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "1", "name": "Alpha"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "2", "name": "Beta"}}),
        )
        result = runner.invoke(
            app,
            [
                "import",
                "board",
                "--board",
                "42",
                "--from",
                str(src),
                "--group",
                "grp_default",
            ],
        )
        assert result.exit_code == 0, result.stdout
        b1 = json.loads(httpx_mock.get_requests()[1].content)
        b2 = json.loads(httpx_mock.get_requests()[2].content)
        assert b1["variables"]["group"] == "grp_a"
        assert b2["variables"]["group"] == "grp_default"


class TestCsvErrors:
    def test_missing_name_column_exits_2(self, tmp_path: Path) -> None:
        # The name-header check happens before the board preflight, so no
        # HTTP mock is needed.
        src = tmp_path / "bad.csv"
        _write_csv(src, ["title,Status", "Alpha,Done"])
        result = runner.invoke(app, ["import", "board", "--board", "42", "--from", str(src)])
        assert result.exit_code == 2
        assert "--name-column" in result.stderr

    def test_file_not_found(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "import",
                "board",
                "--board",
                "42",
                "--from",
                str(tmp_path / "nope.csv"),
            ],
        )
        assert result.exit_code == 2
