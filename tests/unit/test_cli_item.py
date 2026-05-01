"""End-to-end CLI tests for the `mondo item ...` command group."""

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


def _last_body(httpx_mock: HTTPXMock) -> dict:
    """Return the JSON body of the most recent POST."""
    reqs = httpx_mock.get_requests()
    assert reqs, "no requests captured"
    return json.loads(reqs[-1].content)


# --- get ---


class TestItemGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"items": [{"id": "1", "name": "Test", "state": "active"}]}),
        )
        result = runner.invoke(app, ["item", "get", "--id", "1"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Test"
        body = _last_body(httpx_mock)
        assert body["variables"] == {"id": 1}

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"items": []}))
        result = runner.invoke(app, ["item", "get", "--id", "999"])
        assert result.exit_code == 6

    def test_include_updates_uses_updates_query(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"items": [{"id": "1", "name": "T", "updates": []}]}),
        )
        result = runner.invoke(app, ["item", "get", "--id", "1", "--include-updates"])
        assert result.exit_code == 0
        assert "updates" in _last_body(httpx_mock)["query"]

    def test_include_subitems_uses_subitems_query(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"items": [{"id": "1", "name": "T", "subitems": []}]}),
        )
        result = runner.invoke(app, ["item", "get", "--id", "1", "--include-subitems"])
        assert result.exit_code == 0
        assert "subitems" in _last_body(httpx_mock)["query"]

    def test_accepts_pulses_url(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"items": [{"id": "987", "name": "Task"}]}),
        )
        result = runner.invoke(
            app,
            [
                "item",
                "get",
                "https://marktguru.monday.com/boards/42/pulses/987",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert _last_body(httpx_mock)["variables"] == {"id": 987}

    def test_rejects_board_url_with_hint(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["item", "get", "https://marktguru.monday.com/boards/42"],
        )
        assert result.exit_code == 2
        # Rich formats the error into a box; match on the distinctive tail of
        # the hint rather than the whole "mondo board get ..." string (which
        # gets wrapped across box lines).
        assert "board get https://marktguru.monday.com/boards/42" in result.stderr
        assert httpx_mock.get_requests() == []

    def test_with_url_includes_url_field(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {
                            "id": "1",
                            "name": "T",
                            "url": "https://marktguru.monday.com/boards/42/pulses/1",
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["item", "get", "--id", "1", "--with-url"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["url"] == "https://marktguru.monday.com/boards/42/pulses/1"

    def test_without_url_strips_field_from_payload(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "items": [
                        {
                            "id": "1",
                            "name": "T",
                            "url": "https://marktguru.monday.com/boards/42/pulses/1",
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["item", "get", "--id", "1"])
        assert result.exit_code == 0, result.stdout
        assert "url" not in json.loads(result.stdout)

    def test_item_get_selects_url(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"items": [{"id": "1"}]}),
        )
        runner.invoke(app, ["item", "get", "--id", "1"])
        # url is in the selection regardless of --with-url so monday returns it.
        query = _last_body(httpx_mock)["query"]
        assert "\n    url\n" in query or " url " in query


# --- list ---


class TestItemList:
    def test_single_page(self, httpx_mock: HTTPXMock) -> None:
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
                                    {"id": "1", "name": "A"},
                                    {"id": "2", "name": "B"},
                                ],
                            }
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["item", "list", "--board", "42"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert [r["id"] for r in parsed] == ["1", "2"]

    def test_paginates(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"items_page": {"cursor": "C", "items": [{"id": "1"}]}}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"next_items_page": {"cursor": None, "items": [{"id": "2"}]}}),
        )
        result = runner.invoke(app, ["item", "list", "--board", "42"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert [r["id"] for r in parsed] == ["1", "2"]
        assert len(httpx_mock.get_requests()) == 2

    def test_max_items(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "items_page": {
                                "cursor": "C",
                                "items": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
                            }
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["item", "list", "--board", "42", "--max-items", "2"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert [r["id"] for r in parsed] == ["1", "2"]
        assert len(httpx_mock.get_requests()) == 1

    def test_filter_builds_rule(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"items_page": {"cursor": None, "items": []}}]}),
        )
        result = runner.invoke(app, ["item", "list", "--board", "42", "--filter", "status=Done"])
        assert result.exit_code == 0
        qp = _last_body(httpx_mock)["variables"]["qp"]
        assert qp["rules"] == [
            {"column_id": "status", "compare_value": ["Done"], "operator": "any_of"}
        ]

    def test_bad_filter_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["item", "list", "--board", "42", "--filter", "nobareequals"])
        assert result.exit_code == 2
        assert len(httpx_mock.get_requests()) == 0


# --- create ---


class TestItemCreate:
    def test_minimal(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "99", "name": "New"}}),
        )
        result = runner.invoke(app, ["item", "create", "--board", "42", "--name", "New"])
        assert result.exit_code == 0
        body = _last_body(httpx_mock)
        assert body["variables"]["board"] == 42
        assert body["variables"]["name"] == "New"
        assert body["variables"]["values"] is None

    def test_with_codec_dispatch(self, httpx_mock: HTTPXMock) -> None:
        # Preflight: board columns — used by the codec dispatcher
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
                                {"id": "text", "type": "text", "settings_str": "{}"},
                                {
                                    "id": "status",
                                    "type": "status",
                                    "settings_str": json.dumps(
                                        {"labels": {"0": "Working on it", "1": "Done"}}
                                    ),
                                },
                            ],
                        }
                    ]
                }
            ),
        )
        # The create mutation
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "99", "name": "New"}}),
        )
        result = runner.invoke(
            app,
            [
                "item",
                "create",
                "--board",
                "42",
                "--name",
                "New",
                "--column",
                "text=Hello",
                "--column",
                "status=Done",
            ],
        )
        assert result.exit_code == 0, result.stdout
        values = json.loads(_last_body(httpx_mock)["variables"]["values"])
        # Status codec converts "Done" → {"label": "Done"}
        assert values == {"text": "Hello", "status": {"label": "Done"}}

    def test_raw_columns_skips_codec(self, httpx_mock: HTTPXMock) -> None:
        # No preflight when --raw-columns
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "99", "name": "New"}}),
        )
        result = runner.invoke(
            app,
            [
                "item",
                "create",
                "--board",
                "42",
                "--name",
                "New",
                "--raw-columns",
                "--column",
                'status={"label":"Done"}',
            ],
        )
        assert result.exit_code == 0
        values = json.loads(_last_body(httpx_mock)["variables"]["values"])
        assert values == {"status": {"label": "Done"}}
        assert len(httpx_mock.get_requests()) == 1  # no preflight

    def test_dry_run_with_columns_still_does_preflight(self, httpx_mock: HTTPXMock) -> None:
        # With codec dispatch we need the preflight to know column types;
        # only the final `create_item` mutation is skipped under --dry-run.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "name": "B", "columns": []}]}),
        )
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "item",
                "create",
                "--board",
                "42",
                "--name",
                "Hi",
                "--column",
                "text=Hello",
            ],
        )
        assert result.exit_code == 0
        # One preflight, zero mutations
        assert len(httpx_mock.get_requests()) == 1
        parsed = json.loads(result.stdout)
        assert "create_item" in parsed["query"]

    def test_dry_run_no_columns_is_fully_offline(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "item",
                "create",
                "--board",
                "42",
                "--name",
                "Hi",
            ],
        )
        assert result.exit_code == 0
        assert len(httpx_mock.get_requests()) == 0
        parsed = json.loads(result.stdout)
        assert "create_item" in parsed["query"]
        assert parsed["variables"]["name"] == "Hi"

    def test_position_relative_method(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_item": {"id": "99", "name": "New"}}),
        )
        result = runner.invoke(
            app,
            [
                "item",
                "create",
                "--board",
                "42",
                "--name",
                "New",
                "--position-relative-method",
                "after_at",
                "--relative-to",
                "77",
            ],
        )
        assert result.exit_code == 0
        vars_ = _last_body(httpx_mock)["variables"]
        assert vars_["prm"] == "after_at"
        assert vars_["relto"] == 77


# --- rename / duplicate ---


class TestItemRename:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_simple_column_value": {"id": "1", "name": "New name"}}),
        )
        result = runner.invoke(
            app, ["item", "rename", "--id", "1", "--board", "42", "--name", "New name"]
        )
        assert result.exit_code == 0
        body = _last_body(httpx_mock)
        assert body["variables"] == {"board": 42, "id": 1, "name": "New name"}
        assert "change_simple_column_value" in body["query"]
        assert 'column_id: "name"' in body["query"]
        assert "change_item_name" not in body["query"]


class TestItemCreateBatch:
    def test_batch_creates_three_in_one_http_call(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        """Three batch items fan into a single multi-mutation document."""
        batch_file = tmp_path / "items.json"
        batch_file.write_text(
            json.dumps(
                [
                    {"name": "A", "group_id": "topics"},
                    {"name": "B", "group_id": "topics"},
                    {"name": "C", "group_id": "topics"},
                ]
            )
        )
        # One response covers all three aliases.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "data": {
                    "m_0": {"id": "11", "name": "A"},
                    "m_1": {"id": "22", "name": "B"},
                    "m_2": {"id": "33", "name": "C"},
                },
                "extensions": {"request_id": "r"},
            },
        )
        result = runner.invoke(
            app,
            ["item", "create", "--board", "42", "--batch", str(batch_file)],
        )
        assert result.exit_code == 0, result.stdout
        envelope = json.loads(result.stdout)
        assert envelope["summary"] == {"requested": 3, "created": 3, "failed": 0}
        assert [r["id"] for r in envelope["results"]] == ["11", "22", "33"]
        # Single HTTP call, regardless of row count.
        assert len(httpx_mock.get_requests()) == 1
        body = json.loads(httpx_mock.get_requests()[0].content)
        assert "m_0:" in body["query"] and "m_2:" in body["query"]
        # Variables are flattened with per-row suffixes.
        assert body["variables"]["name_0"] == "A"
        assert body["variables"]["name_2"] == "C"

    def test_batch_chunking_splits_into_multiple_calls(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        """5 items + chunk_size=2 -> 3 HTTP calls (2+2+1)."""
        rows = [{"name": chr(ord("A") + i)} for i in range(5)]
        batch_file = tmp_path / "rows.json"
        batch_file.write_text(json.dumps(rows))
        for chunk_idx in range(3):
            httpx_mock.add_response(
                url=ENDPOINT,
                method="POST",
                json={
                    "data": {
                        f"m_{i}": {"id": str(100 + chunk_idx * 10 + i), "name": "x"}
                        for i in range(2 if chunk_idx < 2 else 1)
                    },
                    "extensions": {"request_id": "r"},
                },
            )
        result = runner.invoke(
            app,
            [
                "item", "create",
                "--board", "42",
                "--batch", str(batch_file),
                "--chunk-size", "2",
            ],
        )
        assert result.exit_code == 0, result.stdout
        env = json.loads(result.stdout)
        assert env["summary"]["created"] == 5
        assert len(httpx_mock.get_requests()) == 3
        # Row indices are absolute across chunks.
        assert [r["row_index"] for r in env["results"]] == [0, 1, 2, 3, 4]

    def test_batch_partial_failure_exits_1_with_envelope(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        batch_file = tmp_path / "two.json"
        batch_file.write_text(json.dumps([{"name": "A"}, {"name": "B"}]))
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json={
                "data": {"m_0": {"id": "11", "name": "A"}, "m_1": None},
                "errors": [{"message": "Group not found", "path": ["m_1"]}],
                "extensions": {"request_id": "r"},
            },
        )
        result = runner.invoke(
            app,
            ["item", "create", "--board", "42", "--batch", str(batch_file)],
        )
        assert result.exit_code == 1, result.stdout
        env = json.loads(result.stdout)
        assert env["summary"] == {"requested": 2, "created": 1, "failed": 1}
        assert env["results"][0]["ok"] is True
        assert env["results"][1]["ok"] is False
        assert env["results"][1]["error"] == "Group not found"

    def test_batch_dry_run_emits_chunks_without_calling_api(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        batch_file = tmp_path / "items.json"
        batch_file.write_text(json.dumps([{"name": "A"}, {"name": "B"}, {"name": "C"}]))
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "item", "create", "--board", "42",
                "--batch", str(batch_file),
                "--chunk-size", "2",
            ],
        )
        assert result.exit_code == 0, result.stdout
        env = json.loads(result.stdout)
        assert "chunks" in env
        assert len(env["chunks"]) == 2
        assert env["chunks"][0]["row_indices"] == [0, 1]
        assert env["chunks"][1]["row_indices"] == [2]
        assert "m_0:" in env["chunks"][0]["query"]
        # No HTTP calls were made.
        assert httpx_mock.get_requests() == []

    def test_batch_mutex_with_single_item_flags(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        batch_file = tmp_path / "x.json"
        batch_file.write_text(json.dumps([{"name": "A"}]))
        result = runner.invoke(
            app,
            [
                "item", "create",
                "--board", "42",
                "--name", "X",
                "--batch", str(batch_file),
            ],
        )
        assert result.exit_code == 2, result.stdout

    def test_batch_bad_json_exits_2(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        batch_file = tmp_path / "bad.json"
        batch_file.write_text('{"not": "an array"}')
        result = runner.invoke(
            app,
            ["item", "create", "--board", "42", "--batch", str(batch_file)],
        )
        assert result.exit_code == 2, result.stdout

    def test_batch_missing_name_exits_2(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        batch_file = tmp_path / "noname.json"
        batch_file.write_text(json.dumps([{"group_id": "topics"}]))
        result = runner.invoke(
            app,
            ["item", "create", "--board", "42", "--batch", str(batch_file)],
        )
        assert result.exit_code == 2, result.stdout

    def test_batch_empty_array_exits_2(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        batch_file = tmp_path / "empty.json"
        batch_file.write_text("[]")
        result = runner.invoke(
            app,
            ["item", "create", "--board", "42", "--batch", str(batch_file)],
        )
        assert result.exit_code == 2, result.stdout

    def test_create_without_name_or_batch_exits_2(
        self, httpx_mock: HTTPXMock
    ) -> None:
        result = runner.invoke(app, ["item", "create", "--board", "42"])
        assert result.exit_code == 2, result.stdout


class TestItemRenameByName:
    def test_name_contains_resolves_via_items_page(
        self, httpx_mock: HTTPXMock
    ) -> None:
        # First request: items_page lookup. Second: the rename mutation.
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
                                    {"id": "11", "name": "Apple", "state": "active"},
                                    {"id": "22", "name": "Banana", "state": "active"},
                                ],
                            }
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"change_simple_column_value": {"id": "22", "name": "Cherry"}}),
        )
        result = runner.invoke(
            app,
            [
                "item", "rename",
                "--board", "42",
                "--name-contains", "banana",
                "--name", "Cherry",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"board": 42, "id": 22, "name": "Cherry"}


class TestItemDuplicate:
    def test_with_updates(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_item": {"id": "2", "name": "A copy"}}),
        )
        result = runner.invoke(
            app,
            ["item", "duplicate", "--id", "1", "--board", "42", "--with-updates"],
        )
        assert result.exit_code == 0
        assert _last_body(httpx_mock)["variables"]["with_updates"] is True


# --- archive / delete / move ---


class TestItemArchive:
    def test_requires_confirmation(self, httpx_mock: HTTPXMock) -> None:
        # Pipe stdin: no input → confirmation prompt auto-rejects → exit 1
        result = runner.invoke(app, ["item", "archive", "--id", "1"], input="n\n")
        assert result.exit_code == 1
        assert len(httpx_mock.get_requests()) == 0

    def test_yes_skips_prompt(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"archive_item": {"id": "1", "name": "gone"}}),
        )
        result = runner.invoke(app, ["-y", "item", "archive", "--id", "1"])
        assert result.exit_code == 0

    def test_confirmed_interactive(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"archive_item": {"id": "1", "name": "gone"}}),
        )
        result = runner.invoke(app, ["item", "archive", "--id", "1"], input="y\n")
        assert result.exit_code == 0


class TestItemDelete:
    def test_rejects_without_hard(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["-y", "item", "delete", "--id", "1"])
        assert result.exit_code == 2
        assert len(httpx_mock.get_requests()) == 0

    def test_hard_plus_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_item": {"id": "1", "name": "gone"}}),
        )
        result = runner.invoke(app, ["-y", "item", "delete", "--id", "1", "--hard"])
        assert result.exit_code == 0


class TestItemMove:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"move_item_to_group": {"id": "1", "group": {"id": "g2"}}}),
        )
        result = runner.invoke(app, ["item", "move", "--id", "1", "--group", "topics_two"])
        assert result.exit_code == 0
        body = _last_body(httpx_mock)
        assert body["variables"] == {"id": 1, "group": "topics_two"}


class TestItemMoveToBoard:
    def _success_payload(self) -> dict[str, object]:
        return {
            "move_item_to_board": {
                "id": "1",
                "name": "Thing",
                "state": "active",
                "board": {"id": "99", "name": "Dest"},
                "group": {"id": "g-new", "title": "Group"},
            }
        }

    def test_basic_no_column_mapping(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok(self._success_payload()))
        result = runner.invoke(
            app,
            [
                "item",
                "move-to-board",
                "--id",
                "1",
                "--to-board",
                "99",
                "--to-group",
                "g-new",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["id"] == 1
        assert v["board"] == 99
        assert v["group"] == "g-new"
        assert v["columns"] is None
        assert v["subitemColumns"] is None

    def test_column_mapping_parsed(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok(self._success_payload()))
        result = runner.invoke(
            app,
            [
                "item",
                "move-to-board",
                "--id",
                "1",
                "--to-board",
                "99",
                "--to-group",
                "g-new",
                "--column-mapping",
                "status=state",
                "--column-mapping",
                "date4=due",
                "--column-mapping",
                "notes=",  # drop
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["columns"] == [
            {"source": "status", "target": "state"},
            {"source": "date4", "target": "due"},
            {"source": "notes", "target": None},
        ]
        assert v["subitemColumns"] is None

    def test_subitem_column_mapping(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok(self._success_payload()))
        result = runner.invoke(
            app,
            [
                "item",
                "move-to-board",
                "--id",
                "1",
                "--to-board",
                "99",
                "--to-group",
                "g-new",
                "--subitem-column-mapping",
                "sub_status=sub_state",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["subitemColumns"] == [{"source": "sub_status", "target": "sub_state"}]

    def test_missing_source_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "item",
                "move-to-board",
                "--id",
                "1",
                "--to-board",
                "99",
                "--to-group",
                "g-new",
                "--column-mapping",
                "=target-only",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []
