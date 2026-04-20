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
