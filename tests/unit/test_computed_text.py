"""`text` ← `display_value` fallback on typed reads (#105).

monday returns `text: null` for computed column types (mirror, formula,
board_relation, dependency); agents reading `.text` concluded the columns
were empty and escaped to raw graphql. Typed reads now fill `text` from
`display_value` before emitting.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli._computed_text import fill_computed_text
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


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _mirror_cv(display: str | None) -> dict:
    return {
        "id": "mirror3__1",
        "type": "mirror",
        "text": None,
        "value": None,
        "display_value": display,
    }


class TestFillComputedText:
    def test_fills_null_text_from_display_value(self) -> None:
        item = {"id": "1", "column_values": [_mirror_cv("a@b.com")]}
        fill_computed_text(item)
        assert item["column_values"][0]["text"] == "a@b.com"
        # display_value stays present
        assert item["column_values"][0]["display_value"] == "a@b.com"

    def test_leaves_real_text_alone(self) -> None:
        cv = {"id": "status", "type": "status", "text": "Done", "display_value": "ignored"}
        item = {"column_values": [cv]}
        fill_computed_text(item)
        assert cv["text"] == "Done"

    def test_empty_display_value_keeps_text_null(self) -> None:
        item = {"column_values": [_mirror_cv("")]}
        fill_computed_text(item)
        assert item["column_values"][0]["text"] is None

    def test_recurses_into_subitems(self) -> None:
        item = {
            "column_values": [],
            "subitems": [{"column_values": [_mirror_cv("nested")]}],
        }
        fill_computed_text(item)
        assert item["subitems"][0]["column_values"][0]["text"] == "nested"

    def test_tolerates_odd_shapes(self) -> None:
        # None, non-dict rows, missing column_values — must not raise.
        fill_computed_text(None)
        fill_computed_text([{"id": "1"}, "junk", {"column_values": ["junk", {}]}])  # type: ignore[list-item]


class TestCliFillsComputedText:
    def test_item_list_fills_mirror_text(self, httpx_mock: HTTPXMock) -> None:
        page = {
            "boards": [
                {
                    "items_page": {
                        "cursor": None,
                        "items": [
                            {"id": "1", "name": "Row", "column_values": [_mirror_cv("x@y.com")]},
                        ],
                    }
                }
            ]
        }
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok(page))
        result = runner.invoke(app, ["-o", "json", "item", "list", "--board", "42"])
        assert result.exit_code == 0, result.output
        emitted = json.loads(result.output)
        assert emitted[0]["column_values"][0]["text"] == "x@y.com"

    def test_item_get_fills_mirror_text(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {"id": "7", "name": "One", "column_values": [_mirror_cv("val")]},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["-o", "json", "item", "get", "7"])
        assert result.exit_code == 0, result.output
        emitted = json.loads(result.output)
        assert emitted["column_values"][0]["text"] == "val"

    def test_subitem_list_fills_mirror_text(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {
                            "id": "5",
                            "subitems": [
                                {
                                    "id": "6",
                                    "name": "Sub",
                                    "column_values": [_mirror_cv("sub-val")],
                                },
                            ],
                        },
                    ]
                }
            ),
        )
        result = runner.invoke(
            app, ["-o", "json", "subitem", "list", "--parent", "5", "--no-cache"]
        )
        assert result.exit_code == 0, result.output
        emitted = json.loads(result.output)
        assert emitted[0]["column_values"][0]["text"] == "sub-val"

    def test_column_set_return_fills_mirror_text(self, httpx_mock: HTTPXMock) -> None:
        # The mutation return carries the item's column_values, where computed
        # columns still arrive with text:null — the emit must fill them too.
        context = _ok(
            {
                "items": [
                    {
                        "id": "9",
                        "name": "Row",
                        "board": {
                            "id": "42",
                            "columns": [
                                {"id": "text0", "title": "T", "type": "text", "settings_str": "{}"},
                            ],
                        },
                        "column_values": [
                            {"id": "text0", "type": "text", "text": "", "value": None}
                        ],
                    }
                ]
            }
        )
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=context)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "change_column_value": {
                        "id": "9",
                        "name": "Row",
                        "column_values": [
                            {
                                "id": "text0",
                                "type": "text",
                                "text": "written",
                                "value": '"written"',
                            },
                            _mirror_cv("mirrored"),
                        ],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "-o",
                "json",
                "column",
                "set",
                "--item",
                "9",
                "--column",
                "text0",
                "--value",
                "written",
            ],
        )
        assert result.exit_code == 0, result.output
        emitted = json.loads(result.output)
        by_id = {cv["id"]: cv for cv in emitted["column_values"]}
        assert by_id["mirror3__1"]["text"] == "mirrored"

    def test_column_set_batch_results_fill_mirror_text(self, httpx_mock: HTTPXMock) -> None:
        # Column defs fetch, then one aliased mutation whose per-row returns
        # carry column_values with a computed column.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "name": "B",
                            "columns": [
                                {"id": "text0", "title": "T", "type": "text", "settings_str": "{}"}
                            ],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "m_0": {
                        "id": "1",
                        "name": "a",
                        "column_values": [_mirror_cv("batch-mirrored")],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["-o", "json", "column", "set", "--board", "42", "--column", "text0", "--batch", "-"],
            input=json.dumps([{"item": 1, "value": "A"}]),
        )
        assert result.exit_code == 0, result.output
        env = json.loads(result.output)
        assert env["results"][0]["data"]["column_values"][0]["text"] == "batch-mirrored"
