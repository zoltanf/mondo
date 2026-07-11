"""End-to-end CLI tests for the `mondo column ...` command group."""

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


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _context_response(board_id: int, cols: list[dict], values: list[dict]) -> dict:
    return _ok(
        {
            "items": [
                {
                    "id": "1",
                    "name": "item",
                    "board": {"id": str(board_id), "columns": cols},
                    "column_values": values,
                }
            ]
        }
    )


def _columns_response(board_id: int, cols: list[dict]) -> dict:
    """Shape returned by COLUMNS_ON_BOARD (used by fetch_column_defs)."""
    return _ok({"boards": [{"id": str(board_id), "name": "B", "columns": cols}]})


class TestColumnList:
    def test_emits_simplified_columns(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "name": "Board",
                            "columns": [
                                {"id": "text", "title": "Text", "type": "text", "archived": False},
                                {
                                    "id": "status",
                                    "title": "Status",
                                    "type": "status",
                                    "archived": False,
                                    "settings_str": "{}",
                                },
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["column", "list", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed == [
            {"id": "text", "title": "Text", "type": "text", "archived": False},
            {"id": "status", "title": "Status", "type": "status", "archived": False},
        ]


class TestColumnGetMeta:
    """Friction report B3: agents wanted a single-column metadata fetch
    (rather than `column list` returning *every* column or raw GraphQL).
    """

    def test_returns_single_column_with_settings_str(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "name": "Board",
                            "columns": [
                                {
                                    "id": "status",
                                    "title": "Status",
                                    "type": "status",
                                    "archived": False,
                                    "settings_str": json.dumps(
                                        {"labels": {"0": "New", "1": "Done"}}
                                    ),
                                },
                                {
                                    "id": "name",
                                    "title": "Name",
                                    "type": "name",
                                    "archived": False,
                                    "settings_str": "{}",
                                },
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["column", "get-meta", "--board", "42", "--column", "status"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["id"] == "status"
        assert parsed["title"] == "Status"
        assert parsed["type"] == "status"
        # Crucially: get-meta MUST preserve settings_str (unlike `column list`,
        # which strips it for noise reduction).
        assert "settings_str" in parsed
        assert "labels" in parsed["settings_str"]

    def test_unknown_column_errors_with_clear_message(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "name": "Board",
                            "columns": [
                                {
                                    "id": "name",
                                    "title": "Name",
                                    "type": "name",
                                    "archived": False,
                                    "settings_str": "{}",
                                }
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["column", "get-meta", "--board", "42", "--column", "missing"])
        assert result.exit_code == 6
        combined = (result.stdout or "") + (result.stderr or "")
        assert "missing" in combined.lower() and "not found" in combined.lower()

    def test_board_id_alias_accepted(self, httpx_mock: HTTPXMock) -> None:
        """--board-id should be accepted as a hidden alias (parity with `column list`)."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "name": "Board",
                            "columns": [
                                {
                                    "id": "status",
                                    "title": "Status",
                                    "type": "status",
                                    "archived": False,
                                    "settings_str": "{}",
                                }
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(
            app, ["column", "get-meta", "--board-id", "42", "--column", "status"]
        )
        assert result.exit_code == 0, result.stdout


class TestColumnGet:
    def test_human_rendered(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "status", "title": "S", "type": "status", "settings_str": "{}"}],
                values=[
                    {
                        "id": "status",
                        "type": "status",
                        "text": "Done",
                        "value": '{"index":1}',
                    }
                ],
            ),
        )
        result = runner.invoke(app, ["column", "get", "--item", "1", "--column", "status"])
        assert result.exit_code == 0
        assert result.stdout.strip() == '"Done"'

    def test_raw_emits_envelope(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "text", "title": "T", "type": "text", "settings_str": "{}"}],
                values=[{"id": "text", "type": "text", "text": "Hello", "value": '"Hello"'}],
            ),
        )
        result = runner.invoke(app, ["column", "get", "--item", "1", "--column", "text", "--raw"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["text"] == "Hello"
        assert parsed["type"] == "text"


class TestColumnSet:
    def test_codec_parsed_status(self, httpx_mock: HTTPXMock) -> None:
        # Context fetch
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[
                    {
                        "id": "status",
                        "title": "S",
                        "type": "status",
                        "settings_str": json.dumps({"labels": {"0": "Working on it", "1": "Done"}}),
                    }
                ],
                values=[{"id": "status", "type": "status", "text": "", "value": None}],
            ),
        )
        # Mutation
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1", "name": "item"}}),
        )
        result = runner.invoke(
            app,
            ["column", "set", "--item", "1", "--column", "status", "--value", "Done"],
        )
        assert result.exit_code == 0, result.stdout
        # Last call was the mutation — assert the codec-parsed payload
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == json.dumps({"label": "Done"})

    def test_dry_run_does_not_mutate(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "text", "title": "T", "type": "text", "settings_str": "{}"}],
                values=[{"id": "text", "type": "text", "text": "", "value": None}],
            ),
        )
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "column",
                "set",
                "--item",
                "1",
                "--column",
                "text",
                "--value",
                "Hello",
            ],
        )
        assert result.exit_code == 0
        # Only the context fetch, not a mutation
        assert len(httpx_mock.get_requests()) == 1
        parsed = json.loads(result.stdout)
        assert "change_column_value" in parsed["query"]
        assert parsed["variables"]["value"] == '"Hello"'

    def test_raw_mode_passes_json_through(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "status", "title": "S", "type": "status", "settings_str": "{}"}],
                values=[],
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "set",
                "--item",
                "1",
                "--column",
                "status",
                "--value",
                '{"index":7}',
                "--raw",
            ],
        )
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == json.dumps({"index": 7})

    def test_name_pseudo_column_points_at_item_rename(self, httpx_mock: HTTPXMock) -> None:
        """Issue #11: `--column name` is the item's title, not a settable
        column. The error must contain the exact `mondo item rename`
        invocation instead of the dead-end --raw suggestion."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "name", "title": "Name", "type": "name", "settings_str": "{}"}],
                values=[{"id": "name", "type": "name", "text": "item", "value": None}],
            ),
        )
        result = runner.invoke(
            app,
            ["column", "set", "--item", "1", "--column", "name", "--value", "New title"],
        )
        assert result.exit_code == 5, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "mondo item rename 1 --board 42 --name" in combined
        assert "--raw" not in combined
        # Only the context fetch went out — no mutation was attempted.
        assert len(httpx_mock.get_requests()) == 1

    def test_unknown_type_keeps_generic_no_codec_message(self, httpx_mock: HTTPXMock) -> None:
        """The generic no-codec error (with the --raw suggestion) is
        unchanged for genuinely unknown column types."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "weird", "title": "W", "type": "doc", "settings_str": "{}"}],
                values=[{"id": "weird", "type": "doc", "text": "", "value": None}],
            ),
        )
        result = runner.invoke(
            app,
            ["column", "set", "--item", "1", "--column", "weird", "--value", "x"],
        )
        assert result.exit_code == 5, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "no codec for column type 'doc'" in combined
        assert "--raw" in combined

    def test_tag_names_resolved_to_ids(self, httpx_mock: HTTPXMock) -> None:
        # Context fetch
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "tags", "title": "T", "type": "tags", "settings_str": "{}"}],
                values=[{"id": "tags", "type": "tags", "text": "", "value": None}],
            ),
        )
        # create_or_get_tag x 2
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_or_get_tag": {"id": "1001", "name": "urgent"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_or_get_tag": {"id": "1002", "name": "blocked"}}),
        )
        # Final mutation
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "set",
                "--item",
                "1",
                "--column",
                "tags",
                "--value",
                "urgent,blocked",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == json.dumps({"tag_ids": [1001, 1002]})

    def test_clear_shaped_value_hints_column_clear(self, httpx_mock: HTTPXMock) -> None:
        """#91: an "empty" payload against a dropdown fails the codec and the
        error points at `column clear`."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[
                    {
                        "id": "dd",
                        "title": "D",
                        "type": "dropdown",
                        "settings_str": json.dumps({"labels": [{"id": 1, "name": "Red"}]}),
                    }
                ],
                values=[{"id": "dd", "type": "dropdown", "text": "", "value": None}],
            ),
        )
        result = runner.invoke(
            app,
            ["column", "set", "--item", "1", "--column", "dd", "--value", '{"labels":[]}'],
        )
        assert result.exit_code == 5, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "mondo column clear --item 1 --column dd" in combined
        # No mutation was attempted (only the context fetch).
        assert len(httpx_mock.get_requests()) == 1

    def test_ordinary_bad_value_has_no_clear_hint(self, httpx_mock: HTTPXMock) -> None:
        """The clear hint must not fire on a genuinely wrong label."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[
                    {
                        "id": "dd",
                        "title": "D",
                        "type": "dropdown",
                        "settings_str": json.dumps({"labels": [{"id": 1, "name": "Red"}]}),
                    }
                ],
                values=[{"id": "dd", "type": "dropdown", "text": "", "value": None}],
            ),
        )
        result = runner.invoke(
            app,
            ["column", "set", "--item", "1", "--column", "dd", "--value", "Nope"],
        )
        assert result.exit_code == 5, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "unknown dropdown label" in combined
        assert "mondo column clear" not in combined


_TEXT_COLS = [{"id": "text", "title": "T", "type": "text", "settings_str": "{}"}]


class TestColumnSetBatch:
    def test_sets_three_in_one_mutation_call(self, httpx_mock: HTTPXMock) -> None:
        # Column defs fetch (once for the board), then one aliased mutation.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, _TEXT_COLS))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "data": {
                    "m_0": {"id": "1", "name": "a"},
                    "m_1": {"id": "2", "name": "b"},
                    "m_2": {"id": "3", "name": "c"},
                },
                "extensions": {"request_id": "r"},
            },
        )
        rows = [
            {"item": 1, "value": "A"},
            {"item": "2", "value": "B"},
            {"item": 3, "column": "text", "value": "C"},
        ]
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "text", "--batch", "-"],
            input=json.dumps(rows),
        )
        assert result.exit_code == 0, result.output
        env = json.loads(result.stdout)
        assert env["summary"] == {"requested": 3, "updated": 3, "failed": 0}
        assert [r["name"] for r in env["results"]] == ["1:text", "2:text", "3:text"]
        # defs fetch + one mutation call = 2 HTTP requests total.
        assert len(httpx_mock.get_requests()) == 2
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert "m_0:" in body["query"] and "m_2:" in body["query"]
        assert body["variables"]["item_0"] == 1
        assert body["variables"]["value_2"] == '"C"'

    def test_chunking_splits_calls(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, _TEXT_COLS))
        for chunk_idx in range(3):
            httpx_mock.add_response(
                url=ENDPOINT,
                method="POST",
                json={
                    "data": {
                        f"m_{i}": {"id": str(chunk_idx * 10 + i), "name": "x"}
                        for i in range(2 if chunk_idx < 2 else 1)
                    },
                    "extensions": {"request_id": "r"},
                },
            )
        rows = [{"item": i, "value": str(i)} for i in range(5)]
        result = runner.invoke(
            app,
            [
                "column",
                "set",
                "--board",
                "42",
                "--column",
                "text",
                "--chunk-size",
                "2",
                "--batch",
                "-",
            ],
            input=json.dumps(rows),
        )
        assert result.exit_code == 0, result.output
        env = json.loads(result.stdout)
        assert env["summary"]["updated"] == 5
        # defs fetch + 3 mutation calls.
        assert len(httpx_mock.get_requests()) == 4
        assert [r["row_index"] for r in env["results"]] == [0, 1, 2, 3, 4]

    def test_partial_failure_exits_1(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, _TEXT_COLS))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "data": {"m_0": {"id": "1", "name": "a"}, "m_1": None},
                "errors": [{"message": "Column value error", "path": ["m_1"]}],
                "extensions": {"request_id": "r"},
            },
        )
        rows = [{"item": 1, "value": "A"}, {"item": 2, "value": "B"}]
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "text", "--batch", "-"],
            input=json.dumps(rows),
        )
        assert result.exit_code == 1, result.output
        env = json.loads(result.stdout)
        assert env["summary"] == {"requested": 2, "updated": 1, "failed": 1}
        assert env["results"][0]["ok"] is True
        assert env["results"][1]["ok"] is False
        assert env["results"][1]["error"] == "Column value error"

    def test_mid_batch_http_error_emits_partial_envelope_exits_1(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """An HTTP-layer failure on a later chunk keeps earlier successes and
        marks the failing + not-attempted rows failed, still exiting 1 with a
        full envelope (rather than aborting with the raw error)."""
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, _TEXT_COLS))
        # Chunk 0 (row 0) succeeds.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={"data": {"m_0": {"id": "1", "name": "a"}}, "extensions": {"request_id": "r"}},
        )
        # Chunk 1 (row 1) fails at the HTTP layer (400 -> non-retryable). Chunk
        # 2 (row 2) is never attempted.
        httpx_mock.add_response(url=ENDPOINT, method="POST", status_code=400, json={})
        rows = [{"item": i, "value": str(i)} for i in range(3)]
        result = runner.invoke(
            app,
            [
                "column",
                "set",
                "--board",
                "42",
                "--column",
                "text",
                "--chunk-size",
                "1",
                "--batch",
                "-",
            ],
            input=json.dumps(rows),
        )
        assert result.exit_code == 1, result.output
        env = json.loads(result.stdout)
        assert env["summary"] == {"requested": 3, "updated": 1, "failed": 2}
        assert env["results"][0]["ok"] is True
        assert env["results"][1]["ok"] is False
        assert "HTTP 400" in env["results"][1]["error"]
        assert env["results"][2]["ok"] is False
        assert env["results"][2]["error"].startswith("aborted:")
        # defs fetch + chunk 0 + chunk 1 = 3 calls; chunk 2 never went out.
        assert len(httpx_mock.get_requests()) == 3

    def test_dry_run_raw_is_offline(self, httpx_mock: HTTPXMock) -> None:
        rows = [{"item": 1, "value": {"index": 2}}, {"item": 2, "value": {"index": 3}}]
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "column",
                "set",
                "--board",
                "42",
                "--column",
                "status",
                "--raw",
                "--chunk-size",
                "1",
                "--batch",
                "-",
            ],
            input=json.dumps(rows),
        )
        assert result.exit_code == 0, result.output
        env = json.loads(result.stdout)
        assert len(env["chunks"]) == 2
        assert env["chunks"][0]["row_indices"] == [0]
        assert env["chunks"][1]["row_indices"] == [1]
        assert "m_0:" in env["chunks"][0]["query"]
        assert env["chunks"][0]["variables"]["value_0"] == json.dumps({"index": 2})
        # --raw dry-run touches the network zero times.
        assert httpx_mock.get_requests() == []

    def test_raw_mode_sends_json_verbatim(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={"data": {"m_0": {"id": "1", "name": "a"}}, "extensions": {"request_id": "r"}},
        )
        rows = [{"item": 1, "value": {"index": 7}}]
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "status", "--raw", "--batch", "-"],
            input=json.dumps(rows),
        )
        assert result.exit_code == 0, result.output
        # No defs fetch in raw mode: a single mutation call.
        assert len(httpx_mock.get_requests()) == 1
        body = json.loads(httpx_mock.get_requests()[0].content)
        assert body["variables"]["value_0"] == json.dumps({"index": 7})

    def test_per_row_column_overrides_default(self, httpx_mock: HTTPXMock) -> None:
        cols = [
            {"id": "text", "title": "T", "type": "text", "settings_str": "{}"},
            {"id": "num", "title": "N", "type": "numbers", "settings_str": "{}"},
        ]
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, cols))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "data": {"m_0": {"id": "1", "name": "a"}, "m_1": {"id": "2", "name": "b"}},
                "extensions": {"request_id": "r"},
            },
        )
        rows = [{"item": 1, "value": "hi"}, {"item": 2, "column": "num", "value": "5"}]
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "text", "--batch", "-"],
            input=json.dumps(rows),
        )
        assert result.exit_code == 0, result.output
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["col_0"] == "text"
        assert body["variables"]["col_1"] == "num"

    def test_bad_codec_value_exits_5_naming_row(self, httpx_mock: HTTPXMock) -> None:
        cols = [
            {
                "id": "status",
                "title": "S",
                "type": "status",
                "settings_str": json.dumps({"labels": {"0": "Working on it", "1": "Done"}}),
            }
        ]
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, cols))
        rows = [{"item": 1, "value": "Done"}, {"item": 2, "value": "Nope"}]
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "status", "--batch", "-"],
            input=json.dumps(rows),
        )
        assert result.exit_code == 5, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "row 1" in combined
        # Failed fast before any mutation: only the defs fetch went out.
        assert len(httpx_mock.get_requests()) == 1

    def test_clear_shaped_row_value_hints_column_clear(self, httpx_mock: HTTPXMock) -> None:
        cols = [
            {
                "id": "dd",
                "title": "D",
                "type": "dropdown",
                "settings_str": json.dumps({"labels": [{"id": 1, "name": "Red"}]}),
            }
        ]
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, cols))
        rows = [{"item": 7, "value": '{"labels":[]}'}]
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "dd", "--batch", "-"],
            input=json.dumps(rows),
        )
        assert result.exit_code == 5, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "mondo column clear --item 7 --column dd" in combined

    def test_requires_board(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["column", "set", "--column", "text", "--batch", "-"],
            input=json.dumps([{"item": 1, "value": "A"}]),
        )
        assert result.exit_code == 2, result.output
        assert "--board is required" in ((result.output or "") + (result.stderr or ""))
        assert httpx_mock.get_requests() == []

    def test_board_without_batch_errors(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--item", "1", "--column", "text", "--value", "A"],
        )
        assert result.exit_code == 2, result.output
        assert "--board is only valid with --batch" in (
            (result.output or "") + (result.stderr or "")
        )
        assert httpx_mock.get_requests() == []

    def test_mutex_with_item(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--item", "1", "--batch", "-"],
            input=json.dumps([{"item": 1, "value": "A"}]),
        )
        assert result.exit_code == 2, result.output
        assert httpx_mock.get_requests() == []

    def test_non_array_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "text", "--batch", "-"],
            input='{"item": 1, "value": "A"}',
        )
        assert result.exit_code == 2, result.output
        assert httpx_mock.get_requests() == []

    def test_empty_array_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "text", "--batch", "-"],
            input="[]",
        )
        assert result.exit_code == 2, result.output
        assert httpx_mock.get_requests() == []

    def test_row_missing_item_exits_2(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, _TEXT_COLS))
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "text", "--batch", "-"],
            input=json.dumps([{"value": "A"}]),
        )
        assert result.exit_code == 2, result.output
        assert "row 0" in ((result.output or "") + (result.stderr or ""))

    def test_row_missing_value_exits_2(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, _TEXT_COLS))
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "text", "--batch", "-"],
            input=json.dumps([{"item": 1}]),
        )
        assert result.exit_code == 2, result.output
        assert "row 0" in ((result.output or "") + (result.stderr or ""))

    def test_row_no_column_no_default_exits_2(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, _TEXT_COLS))
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--batch", "-"],
            input=json.dumps([{"item": 1, "value": "A"}]),
        )
        assert result.exit_code == 2, result.output
        assert "row 0" in ((result.output or "") + (result.stderr or ""))

    def test_structured_value_without_raw_exits_5(self, httpx_mock: HTTPXMock) -> None:
        # A dict/list value can't feed a codec: it's a ValidationError (exit 5)
        # that points at --raw, not the old exit-2 "must be a string".
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, _TEXT_COLS))
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "text", "--batch", "-"],
            input=json.dumps([{"item": 1, "value": {"a": 1}}]),
        )
        assert result.exit_code == 5, result.output
        assert "--raw" in ((result.output or "") + (result.stderr or ""))
        # Failed before any mutation: only the defs fetch went out.
        assert len(httpx_mock.get_requests()) == 1

    def test_scalar_value_stringified_in_codec_mode(self, httpx_mock: HTTPXMock) -> None:
        # Natural JSON like {"item":1,"value":5} for a numbers column: the bare
        # scalar is stringified and fed to the codec (no --raw needed).
        cols = [{"id": "num", "title": "N", "type": "numbers", "settings_str": "{}"}]
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, cols))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={"data": {"m_0": {"id": "1", "name": "a"}}, "extensions": {"request_id": "r"}},
        )
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "num", "--batch", "-"],
            input=json.dumps([{"item": 1, "value": 5}]),
        )
        assert result.exit_code == 0, result.output
        body = json.loads(httpx_mock.get_requests()[-1].content)
        # numbers codec renders the scalar to the string "5".
        assert body["variables"]["value_0"] == '"5"'

    def test_float_item_id_rejected_naming_row(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, _TEXT_COLS))
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "text", "--batch", "-"],
            input=json.dumps([{"item": 1.9, "value": "A"}]),
        )
        assert result.exit_code == 2, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "row 0" in combined and "integer id" in combined
        # Never dispatched a mutation.
        assert all(b"change_column_value" not in r.content for r in httpx_mock.get_requests())

    def test_bool_item_id_rejected(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, _TEXT_COLS))
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "text", "--batch", "-"],
            input=json.dumps([{"item": True, "value": "A"}]),
        )
        assert result.exit_code == 2, result.output
        assert "integer id" in ((result.output or "") + (result.stderr or ""))

    def test_name_pseudo_column_points_at_item_rename(self, httpx_mock: HTTPXMock) -> None:
        cols = [{"id": "name", "title": "Name", "type": "name", "settings_str": "{}"}]
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, cols))
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "name", "--batch", "-"],
            input=json.dumps([{"item": 7, "value": "New title"}]),
        )
        assert result.exit_code == 5, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "mondo item rename" in combined
        # Failed fast at preflight — no mutation dispatched.
        assert len(httpx_mock.get_requests()) == 1

    def test_name_pseudo_column_rejected_in_raw_mode_too(self) -> None:
        # --raw skips the codec but the `name` guard must still fire: the
        # title is never settable via change_column_value. Fully offline.
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "name", "--raw", "--batch", "-"],
            input=json.dumps([{"item": 7, "value": "New title"}]),
        )
        assert result.exit_code == 5, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "mondo item rename" in combined

    def test_dry_run_tag_names_issue_no_mutation(self, httpx_mock: HTTPXMock) -> None:
        # A tags value given as names can't be resolved in --dry-run without a
        # real create_or_get_tag mutation, so it errors instead of writing.
        cols = [{"id": "tags", "title": "Tags", "type": "tags", "settings_str": "{}"}]
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, cols))
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "column",
                "set",
                "--board",
                "42",
                "--column",
                "tags",
                "--batch",
                "-",
            ],
            input=json.dumps([{"item": 1, "value": "urgent,blocked"}]),
        )
        assert result.exit_code == 5, result.output
        assert "tag ids in --dry-run" in ((result.output or "") + (result.stderr or ""))
        # Only the read-only defs fetch happened; create_or_get_tag never fired.
        assert all(b"create_or_get_tag" not in r.content for r in httpx_mock.get_requests())

    def test_dry_run_tag_ids_pass_through(self, httpx_mock: HTTPXMock) -> None:
        # Numeric tag ids need no resolution, so --dry-run works offline-ish
        # (only the read-only defs fetch).
        cols = [{"id": "tags", "title": "Tags", "type": "tags", "settings_str": "{}"}]
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, cols))
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "column",
                "set",
                "--board",
                "42",
                "--column",
                "tags",
                "--batch",
                "-",
            ],
            input=json.dumps([{"item": 1, "value": "1001,1002"}]),
        )
        assert result.exit_code == 0, result.output
        env = json.loads(result.stdout)
        assert env["chunks"][0]["variables"]["value_0"] == json.dumps({"tag_ids": [1001, 1002]})
        assert all(b"create_or_get_tag" not in r.content for r in httpx_mock.get_requests())

    def test_tag_minting_deferred_until_whole_batch_validates(self, httpx_mock: HTTPXMock) -> None:
        """A later row's codec error aborts with nothing minted: tag-name
        resolution (create_or_get_tag) is deferred until every row validates,
        so an earlier tags-by-name row leaves no half-created tags behind."""
        cols = [
            {"id": "tags", "title": "Tags", "type": "tags", "settings_str": "{}"},
            {
                "id": "status",
                "title": "S",
                "type": "status",
                "settings_str": json.dumps({"labels": {"0": "Working on it", "1": "Done"}}),
            },
        ]
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, cols))
        rows = [
            {"item": 1, "column": "tags", "value": "urgent,blocked"},
            {"item": 2, "column": "status", "value": "Nope"},  # invalid label
        ]
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--batch", "-"],
            input=json.dumps(rows),
        )
        assert result.exit_code != 0, result.output
        assert result.exit_code == 5, result.output
        # Failed before phase 2, so no tag was ever minted; only defs fetched.
        assert all(b"create_or_get_tag" not in r.content for r in httpx_mock.get_requests())
        assert len(httpx_mock.get_requests()) == 1

    def test_tag_names_resolved_when_batch_valid(self, httpx_mock: HTTPXMock) -> None:
        """Happy path: once the whole batch validates, phase 2 resolves tag
        names to ids (one create_or_get_tag) and the mutation carries them."""
        cols = [{"id": "tags", "title": "Tags", "type": "tags", "settings_str": "{}"}]
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_columns_response(42, cols))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_or_get_tag": {"id": "1001", "name": "urgent"}}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={"data": {"m_0": {"id": "1", "name": "a"}}, "extensions": {"request_id": "r"}},
        )
        result = runner.invoke(
            app,
            ["column", "set", "--board", "42", "--column", "tags", "--batch", "-"],
            input=json.dumps([{"item": 1, "value": "urgent"}]),
        )
        assert result.exit_code == 0, result.output
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value_0"] == json.dumps({"tag_ids": [1001]})

    def test_bad_board_surfaces_not_found(self, httpx_mock: HTTPXMock) -> None:
        # An inaccessible/missing board yields no column defs; batch mode must
        # report board-not-found (exit 6), not a misleading column-not-found.
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(
            app,
            ["column", "set", "--board", "999", "--column", "text", "--batch", "-"],
            input=json.dumps([{"item": 1, "value": "A"}]),
        )
        assert result.exit_code == 6, result.output
        assert "board 999 not found" in ((result.output or "") + (result.stderr or ""))


class TestColumnSetMany:
    def test_bulk(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[
                    {"id": "text", "title": "T", "type": "text", "settings_str": "{}"},
                    {"id": "status", "title": "S", "type": "status", "settings_str": "{}"},
                ],
                values=[],
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_multiple_column_values": {"id": "1", "name": "item"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "set-many",
                "--item",
                "1",
                "--values",
                '{"text":"Hello","status":{"label":"Done"}}',
            ],
        )
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        values = json.loads(body["variables"]["values"])
        assert values == {"text": "Hello", "status": {"label": "Done"}}


class TestColumnClear:
    def test_checkbox_sends_null(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "done", "title": "D", "type": "checkbox", "settings_str": "{}"}],
                values=[],
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1"}}),
        )
        result = runner.invoke(app, ["column", "clear", "--item", "1", "--column", "done"])
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == "null"

    def test_text_sends_empty_string(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "notes", "title": "N", "type": "text", "settings_str": "{}"}],
                values=[],
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1"}}),
        )
        result = runner.invoke(app, ["column", "clear", "--item", "1", "--column", "notes"])
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == '""'

    def test_status_sends_empty_object(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_context_response(
                board_id=42,
                cols=[{"id": "status", "title": "S", "type": "status", "settings_str": "{}"}],
                values=[],
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_value": {"id": "1"}}),
        )
        result = runner.invoke(app, ["column", "clear", "--item", "1", "--column", "status"])
        assert result.exit_code == 0
        body = json.loads(httpx_mock.get_requests()[-1].content)
        assert body["variables"]["value"] == "{}"


# --- 2b: structural mutations ---


class TestColumnCreate:
    def test_minimal(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_column": {"id": "priority", "title": "Priority", "type": "status"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "Priority",
                "--type",
                "status",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = json.loads(httpx_mock.get_requests()[-1].content)
        v = body["variables"]
        assert v["board"] == 42
        assert v["title"] == "Priority"
        assert v["type"] == "status"
        assert v["description"] is None
        assert v["defaults"] is None
        assert v["id"] is None
        assert v["after"] is None

    def test_with_defaults_gets_json_string(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_column": {"id": "priority"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "P",
                "--type",
                "status",
                "--defaults",
                '{"labels":{"1":"High"}}',
                "--id",
                "priority",
                "--after",
                "status_1",
                "--description",
                "desc",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        # defaults should be a JSON-stringified string, not a dict (§11.4 double-JSON)
        assert isinstance(v["defaults"], str)
        assert json.loads(v["defaults"]) == {"labels": {"1": "High"}}
        assert v["id"] == "priority"
        assert v["after"] == "status_1"
        assert v["description"] == "desc"

    def test_invalid_defaults_json_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "P",
                "--type",
                "status",
                "--defaults",
                "{not json",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "P",
                "--type",
                "status",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "create_column" in parsed["query"]
        assert httpx_mock.get_requests() == []

    def test_labels_status_builds_defaults(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_column": {"id": "stage"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "Stage",
                "--type",
                "status",
                "--labels",
                "A,B,C",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert isinstance(v["defaults"], str)
        assert json.loads(v["defaults"]) == {"labels": {"1": "A", "2": "B", "3": "C"}}

    def test_labels_dropdown_builds_defaults(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_column": {"id": "stack"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "Stack",
                "--type",
                "dropdown",
                "--labels",
                "X,Y",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert json.loads(v["defaults"]) == {
            "settings": {"labels": [{"id": 1, "name": "X"}, {"id": 2, "name": "Y"}]}
        }

    def test_labels_trims_and_drops_empty(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_column": {"id": "stage"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "Stage",
                "--type",
                "status",
                "--labels",
                " A , ,B ,,",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert json.loads(v["defaults"]) == {"labels": {"1": "A", "2": "B"}}

    def test_labels_wrong_type_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "P",
                "--type",
                "text",
                "--labels",
                "A,B",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_labels_with_defaults_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "P",
                "--type",
                "status",
                "--labels",
                "A,B",
                "--defaults",
                '{"labels":{"1":"High"}}',
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_labels_all_empty_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "column",
                "create",
                "--board",
                "42",
                "--title",
                "P",
                "--type",
                "status",
                "--labels",
                " , ,",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


class TestColumnRename:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_title": {"id": "status", "title": "Renamed"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "rename",
                "--board",
                "42",
                "--id",
                "status",
                "--title",
                "Renamed",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert v == {"board": 42, "col": "status", "title": "Renamed"}

    def test_name_contains_resolves_by_title(self, httpx_mock: HTTPXMock) -> None:
        # Cache is disabled in this test fixture, so the columns fetch is live.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "columns": [
                                {"id": "status", "title": "Status", "type": "status"},
                                {"id": "owner", "title": "Owner", "type": "people"},
                            ],
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_title": {"id": "status", "title": "Workflow"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "rename",
                "--board",
                "42",
                "--name-contains",
                "status",
                "--title",
                "Workflow",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert v == {"board": 42, "col": "status", "title": "Workflow"}


class TestColumnChangeMetadata:
    def test_description(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_column_metadata": {"id": "status", "description": "x"}}),
        )
        result = runner.invoke(
            app,
            [
                "column",
                "change-metadata",
                "--board",
                "42",
                "--id",
                "status",
                "--property",
                "description",
                "--value",
                "x",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert v == {
            "board": 42,
            "col": "status",
            "property": "description",
            "value": "x",
        }

    def test_invalid_property(self, httpx_mock: HTTPXMock) -> None:
        # Only title / description are allowed; Typer validates the enum.
        result = runner.invoke(
            app,
            [
                "column",
                "change-metadata",
                "--board",
                "42",
                "--id",
                "status",
                "--property",
                "type",
                "--value",
                "x",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


class TestColumnDelete:
    def test_requires_confirmation(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["column", "delete", "--board", "42", "--id", "status"],
            input="n\n",
        )
        assert result.exit_code == 1
        assert httpx_mock.get_requests() == []

    def test_yes_skips_prompt(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_column": {"id": "status", "archived": True}}),
        )
        result = runner.invoke(
            app,
            ["--yes", "column", "delete", "--board", "42", "--id", "status"],
        )
        assert result.exit_code == 0, result.stdout
        v = json.loads(httpx_mock.get_requests()[-1].content)["variables"]
        assert v == {"board": 42, "col": "status"}

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["--yes", "--dry-run", "column", "delete", "--board", "42", "--id", "status"],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "delete_column" in parsed["query"]
        assert httpx_mock.get_requests() == []
