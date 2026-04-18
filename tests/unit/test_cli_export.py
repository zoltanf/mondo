"""End-to-end CLI tests for `mondo export board ...`."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook
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
                    {"id": "status", "title": "Status", "type": "status", "archived": False},
                    {"id": "date4", "title": "Due", "type": "date", "archived": False},
                    {
                        "id": "archived_col",
                        "title": "Old",
                        "type": "text",
                        "archived": True,
                    },
                ],
            }
        ]
    }
)


def _items_page(items: list[dict], cursor: str | None = None) -> dict:
    return _ok(
        {
            "boards": [
                {"items_page": {"cursor": cursor, "items": items}},
            ]
        }
    )


def _item(id_: str, name: str, cols: dict[str, str], group: str = "topics") -> dict:
    return {
        "id": id_,
        "name": name,
        "state": "active",
        "group": {"id": group, "title": group.title()},
        "column_values": [
            {"id": cid, "type": "text", "text": val, "value": None} for cid, val in cols.items()
        ],
    }


# --- format tests ---


class TestCsvExport:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_items_page(
                [
                    _item("1", "Alpha", {"status": "Done", "date4": "2026-04-25"}),
                    _item("2", "Beta", {"status": "Working on it", "date4": ""}),
                ]
            ),
        )
        result = runner.invoke(app, ["export", "board", "--board", "42", "--format", "csv"])
        assert result.exit_code == 0, result.stdout
        rows = list(csv.reader(io.StringIO(result.stdout)))
        assert rows[0] == ["id", "name", "state", "group", "Status", "Due"]
        assert rows[1][4] == "Done"
        assert rows[2][0] == "2"

    def test_omits_archived_columns(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_items_page([_item("1", "X", {})])
        )
        result = runner.invoke(app, ["export", "board", "--board", "42", "-f", "csv"])
        assert result.exit_code == 0, result.stdout
        # "Old" is archived — should not appear in headers
        first_line = result.stdout.splitlines()[0]
        assert "Old" not in first_line

    def test_tsv_delimiter(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=_items_page([_item("1", "A", {})])
        )
        result = runner.invoke(app, ["export", "board", "--board", "42", "-f", "tsv"])
        assert result.exit_code == 0, result.stdout
        assert "\t" in result.stdout.splitlines()[0]

    def test_writes_to_file(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_items_page([_item("1", "A", {"status": "Done"})]),
        )
        out = tmp_path / "board.csv"
        result = runner.invoke(
            app,
            ["export", "board", "--board", "42", "-f", "csv", "--out", str(out)],
        )
        assert result.exit_code == 0, result.stdout
        content = out.read_text()
        assert "id,name,state,group,Status,Due" in content


class TestJsonExport:
    def test_shape(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_items_page([_item("1", "A", {"status": "Done"})]),
        )
        result = runner.invoke(app, ["export", "board", "--board", "42", "-f", "json"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "items" in parsed
        assert parsed["items"][0]["Status"] == "Done"
        assert "subitems" not in parsed


class TestMarkdownExport:
    def test_pipe_table(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_items_page([_item("1", "A", {"status": "Done"})]),
        )
        result = runner.invoke(app, ["export", "board", "--board", "42", "-f", "md"])
        assert result.exit_code == 0, result.stdout
        assert result.stdout.startswith("| id |")
        assert "|---|" in result.stdout


class TestXlsxExport:
    def test_requires_out(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["export", "board", "--board", "42", "-f", "xlsx"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_writes_workbook(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_items_page([_item("1", "A", {"status": "Done"})]),
        )
        out = tmp_path / "board.xlsx"
        result = runner.invoke(
            app,
            ["export", "board", "--board", "42", "-f", "xlsx", "--out", str(out)],
        )
        assert result.exit_code == 0, result.stdout
        wb = load_workbook(out)
        ws = wb["items"]
        headers = [c.value for c in ws[1]]
        assert headers == ["id", "name", "state", "group", "Status", "Due"]
        row2 = [c.value for c in ws[2]]
        assert row2[0] == "1"
        assert row2[4] == "Done"


# --- subitems ---


class TestIncludeSubitems:
    def test_uses_with_subitems_query(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_items_page(
                [
                    {
                        **_item("1", "Parent", {"status": "Done"}),
                        "subitems": [
                            {
                                "id": "10",
                                "name": "Child A",
                                "state": "active",
                                "column_values": [
                                    {"id": "status", "text": "In progress", "type": "status"}
                                ],
                            }
                        ],
                    }
                ]
            ),
        )
        result = runner.invoke(
            app,
            [
                "export",
                "board",
                "--board",
                "42",
                "-f",
                "json",
                "--include-subitems",
            ],
        )
        assert result.exit_code == 0, result.stdout
        # Items-page request must be the subitems variant
        items_body = json.loads(httpx_mock.get_requests()[-1].content)
        assert "subitems" in items_body["query"]
        parsed = json.loads(result.stdout)
        assert parsed["subitems"][0]["parent_item_id"] == "1"
        assert parsed["subitems"][0]["Status"] == "In progress"

    def test_xlsx_emits_subitems_sheet(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_items_page(
                [
                    {
                        **_item("1", "P", {}),
                        "subitems": [
                            {
                                "id": "10",
                                "name": "Sub",
                                "state": "active",
                                "column_values": [],
                            }
                        ],
                    }
                ]
            ),
        )
        out = tmp_path / "b.xlsx"
        result = runner.invoke(
            app,
            [
                "export",
                "board",
                "--board",
                "42",
                "-f",
                "xlsx",
                "--out",
                str(out),
                "--include-subitems",
            ],
        )
        assert result.exit_code == 0, result.stdout
        wb = load_workbook(out)
        assert "items" in wb.sheetnames
        assert "subitems" in wb.sheetnames


# --- pagination ---


class TestPagination:
    def test_follows_cursor(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=COLS_RESPONSE)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_items_page([_item("1", "A", {})], cursor="C"),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"next_items_page": {"cursor": None, "items": [_item("2", "B", {})]}}),
        )
        result = runner.invoke(app, ["export", "board", "--board", "42", "-f", "json"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [i["id"] for i in parsed["items"]] == ["1", "2"]
