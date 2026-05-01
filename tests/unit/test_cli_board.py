"""End-to-end CLI tests for the `mondo board ...` command group."""

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
    # Default these tests to the live (non-cache) path; cache-specific tests
    # opt back in by re-setting MONDO_CACHE_ENABLED=true.
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _last_body(httpx_mock: HTTPXMock) -> dict:
    reqs = httpx_mock.get_requests()
    assert reqs, "no requests captured"
    return json.loads(reqs[-1].content)


def _bodies(httpx_mock: HTTPXMock) -> list[dict]:
    return [json.loads(r.content) for r in httpx_mock.get_requests()]


# --- list ---


class TestBoardList:
    def test_single_page(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]}),
        )
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["1", "2"]

    def test_paginates_until_short_page(self, httpx_mock: HTTPXMock) -> None:
        # First page is full (limit=2) → fetcher goes for page 2.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "1"}, {"id": "2"}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "3"}]}),
        )
        result = runner.invoke(app, ["board", "list", "--limit", "2"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["1", "2", "3"]
        bodies = _bodies(httpx_mock)
        assert bodies[0]["variables"]["page"] == 1
        assert bodies[1]["variables"]["page"] == 2

    def test_max_items_truncates(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}),
        )
        result = runner.invoke(app, ["board", "list", "--max-items", "2"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert len(parsed) == 2

    def test_name_contains_filters_client_side(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {"id": "1", "name": "Pager Duty"},
                        {"id": "2", "name": "Marketing"},
                        {"id": "3", "name": "pager upgrade"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "list", "--name-contains", "pager"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["1", "3"]

    def test_name_matches_regex(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {"id": "1", "name": "team-alpha"},
                        {"id": "2", "name": "team-beta"},
                        {"id": "3", "name": "other"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "list", "--name-matches", r"^team-\w+$"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["1", "2"]

    def test_name_filters_mutually_exclusive(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["board", "list", "--name-contains", "x", "--name-matches", "y"],
        )
        assert result.exit_code == 2
        # No HTTP should have been made.
        assert httpx_mock.get_requests() == []

    def test_invalid_regex_usage_error(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["board", "list", "--name-matches", "["])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_passes_state_kind_workspace(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(
            app,
            [
                "board",
                "list",
                "--state",
                "active",
                "--kind",
                "public",
                "--workspace",
                "42",
                "--workspace",
                "43",
                "--order-by",
                "used_at",
            ],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"]["state"] == "active"
        assert body["variables"]["kind"] == "public"
        assert body["variables"]["workspaceIds"] == [42, 43]
        assert body["variables"]["orderBy"] == "used_at"

    def test_query_includes_nested_workspace(self, httpx_mock: HTTPXMock) -> None:
        """The boards-list selection set must include the nested
        `workspace { id name }` so JMESPath projections like
        `[*].workspace.name` work — both on the live path and (via the
        same query) when populating the cache."""
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "workspace { id name }" in body["query"]

    def test_omits_unset_filter_args(self, httpx_mock: HTTPXMock) -> None:
        """Monday drops arbitrary boards when `workspace_ids: null` is sent as
        a variable. We build the query dynamically so unset filters are
        absent from both the variables dict and the query string."""
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert set(body["variables"].keys()) == {"limit", "page"}
        for forbidden in ("$state", "$kind", "$workspaceIds", "$orderBy", "$ids"):
            assert forbidden not in body["query"], body["query"]
        for forbidden in ("workspace_ids", "state:", "board_kind:", "order_by:"):
            assert forbidden not in body["query"], body["query"]

    def test_type_filter_hides_docs_by_default(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {"id": "1", "name": "Real board", "type": "board"},
                        {"id": "2", "name": "A doc", "type": "document"},
                        {"id": "3", "name": "No type"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        # Missing `type` falls back to "board" so pre-type entries aren't lost.
        assert [b["id"] for b in parsed] == ["1", "3"]

    def test_type_filter_doc_keeps_only_documents(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {"id": "1", "type": "board"},
                        {"id": "2", "type": "document"},
                        {"id": "3", "type": "sub_items_board"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "list", "--type", "doc"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["2"]

    def test_type_filter_all_passes_everything(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {"id": "1", "type": "board"},
                        {"id": "2", "type": "document"},
                        {"id": "3", "type": "sub_items_board"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "list", "--type", "all"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [b["id"] for b in parsed] == ["1", "2", "3"]

    def test_type_field_included_in_query(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        # `type` is now part of the selection set so the client can filter.
        # Match as a word so it isn't a false hit on "items_count" etc.
        query = _last_body(httpx_mock)["query"]
        assert " type " in query or "\ntype\n" in query or "type\n" in query

    def test_hierarchy_types_included_in_query(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        query = _last_body(httpx_mock)["query"]
        assert "hierarchy_types: [classic, multi_level]" in query

    def test_hierarchy_type_passes_through_output(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "1",
                            "name": "Roadmap",
                            "hierarchy_type": "multi_level",
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed[0]["hierarchy_type"] == "multi_level"

    def test_items_count_omitted_by_default(self, httpx_mock: HTTPXMock) -> None:
        """items_count costs ~500k complexity per page; opt-in only."""
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        assert "items_count" not in _last_body(httpx_mock)["query"]

    def test_created_at_field_included_in_query(self, httpx_mock: HTTPXMock) -> None:
        """board list emits created_at so it can align with doc list's shape."""
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        assert "created_at" in _last_body(httpx_mock)["query"]

    def test_output_uses_kind_not_board_kind(self, httpx_mock: HTTPXMock) -> None:
        """board_kind → kind at the output layer (tier-1 hard rename)."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"boards": [{"id": "1", "name": "X", "board_kind": "public"}]}
            ),
        )
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed[0]["kind"] == "public"
        assert "board_kind" not in parsed[0]

    def test_output_uses_folder_id_not_board_folder_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"boards": [{"id": "1", "name": "X", "board_folder_id": "42"}]}
            ),
        )
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed[0]["folder_id"] == "42"
        assert "board_folder_id" not in parsed[0]

    def test_with_item_counts_flag_includes_items_count(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["board", "list", "--with-item-counts"])
        assert result.exit_code == 0, result.stdout
        assert "items_count" in _last_body(httpx_mock)["query"]

    def test_dry_run_no_http(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["--dry-run", "board", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "boards(" in parsed["query"]
        assert httpx_mock.get_requests() == []

    def test_workspace_pair_adjacent_and_timestamps_at_end(
        self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Enable cache path so workspace_name enrichment runs.
        monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "1",
                            "name": "A",
                            "workspace_id": "42",
                            "board_kind": "public",
                            "created_at": "2024-01-01T00:00:00Z",
                            "updated_at": "2024-02-01T00:00:00Z",
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"workspaces": [{"id": "42", "name": "Engineering"}]}),
        )
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        row = json.loads(result.stdout)[0]
        keys = list(row.keys())
        assert keys[keys.index("workspace_id") + 1] == "workspace_name"
        assert keys[-2:] == ["created_at", "updated_at"]


# --- get ---


class TestBoardGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "name": "Roadmap", "state": "active"}]}),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Roadmap"
        assert _last_body(httpx_mock)["variables"] == {"id": 42}

    def test_hierarchy_type_passes_through(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "name": "Roadmap",
                            "hierarchy_type": "multi_level",
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["hierarchy_type"] == "multi_level"

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["board", "get", "--id", "999"])
        assert result.exit_code == 6

    def test_warns_when_id_is_workdoc(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {"boards": [{"id": "42", "name": "Spec doc", "type": "document"}]}
            ),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["type"] == "document"
        assert "workdoc" in result.stderr
        assert "mondo doc get --object-id 42" in result.stderr

    def test_no_warning_for_regular_board(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "name": "X", "type": "board"}]}),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        assert "workdoc" not in result.stderr

    def test_accepts_url(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "name": "X", "type": "board"}]}),
        )
        result = runner.invoke(
            app,
            [
                "board",
                "get",
                "https://marktguru.monday.com/boards/42/views/1",
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert _last_body(httpx_mock)["variables"] == {"id": 42}

    def test_accepts_pulses_url_and_extracts_board_part(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "name": "X", "type": "board"}]}),
        )
        result = runner.invoke(
            app,
            ["board", "get", "https://marktguru.monday.com/boards/42/pulses/987"],
        )
        assert result.exit_code == 0, result.stdout
        assert _last_body(httpx_mock)["variables"] == {"id": 42}

    def test_rejects_garbage_url(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["board", "get", "not-a-number"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_with_url_adds_synthesized_url(
        self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mondo.cli import _url as url_mod

        monkeypatch.setattr(url_mod, "_TENANT_SLUG_CACHE", None)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "name": "X", "type": "board"}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"me": {"account": {"slug": "marktguru"}}}),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42", "--with-url"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["url"] == "https://marktguru.monday.com/boards/42"

    def test_without_url_payload_has_no_url_key(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "name": "X", "type": "board"}]}),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        assert "url" not in json.loads(result.stdout)

    def test_normalizes_kind_and_folder_id(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "name": "X",
                            "type": "board",
                            "board_kind": "public",
                            "board_folder_id": "7",
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["kind"] == "public"
        assert parsed["folder_id"] == "7"
        assert "board_kind" not in parsed
        assert "board_folder_id" not in parsed

    def test_updated_at_is_last_even_with_url(self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
        from mondo.cli import _url as url_mod

        monkeypatch.setattr(url_mod, "_TENANT_SLUG_CACHE", None)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "name": "X",
                            "type": "board",
                            "updated_at": "2024-02-01T00:00:00Z",
                        }
                    ]
                }
            ),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"me": {"account": {"slug": "marktguru"}}}),
        )
        result = runner.invoke(app, ["board", "get", "--id", "42", "--with-url"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert list(parsed.keys())[-1] == "updated_at"

    def test_dump_spec_reports_integer_for_id(self) -> None:
        result = runner.invoke(app, ["-o", "json", "help", "--dump-spec"])
        assert result.exit_code == 0, result.stdout
        spec = json.loads(result.stdout)
        board = next(c for c in spec["root"]["commands"] if c["name"] == "board")
        get = next(c for c in board["commands"] if c["name"] == "get")
        id_param = next(p for p in get["params"] if p["name"] == "id_flag")
        assert id_param["type"] == "integer"


# --- create ---


class TestBoardCreate:
    def test_minimal(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "create_board": {
                        "id": "99",
                        "name": "New",
                        "board_kind": "public",
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["board", "create", "--name", "New"],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert body["variables"]["name"] == "New"
        assert body["variables"]["kind"] == "public"
        parsed = json.loads(result.stdout)
        assert parsed["kind"] == "public"
        assert "board_kind" not in parsed

    def test_full_options(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_board": {"id": "1"}}),
        )
        result = runner.invoke(
            app,
            [
                "board",
                "create",
                "--name",
                "X",
                "--kind",
                "private",
                "--description",
                "desc",
                "--workspace",
                "7",
                "--folder",
                "8",
                "--owner",
                "42",
                "--owner",
                "43",
                "--subscriber",
                "51",
                "--empty",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["kind"] == "private"
        assert v["description"] == "desc"
        assert v["workspace"] == 7
        assert v["folder"] == 8
        assert v["ownerIds"] == [42, 43]
        assert v["subscriberIds"] == [51]
        assert v["empty"] is True

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "--dry-run",
                "board",
                "create",
                "--name",
                "X",
                "--kind",
                "public",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "create_board" in parsed["query"]
        assert parsed["variables"]["name"] == "X"
        assert httpx_mock.get_requests() == []


# --- update ---


class TestBoardUpdate:
    def test_change_name_emits_object_payload(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_board": {"success": True, "board_id": "42"}}),
        )
        result = runner.invoke(
            app,
            [
                "board",
                "update",
                "--id",
                "42",
                "--attribute",
                "name",
                "--value",
                "Renamed",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed == {"success": True, "board_id": "42"}
        v = _last_body(httpx_mock)["variables"]
        assert v == {"board": 42, "attribute": "name", "value": "Renamed"}

    def test_legacy_json_string_payload_is_parsed(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_board": '{"success": true}'}),
        )
        result = runner.invoke(
            app,
            [
                "board",
                "update",
                "--id",
                "42",
                "--attribute",
                "name",
                "--value",
                "Renamed",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed == {"success": True}
        v = _last_body(httpx_mock)["variables"]
        assert v == {"board": 42, "attribute": "name", "value": "Renamed"}

    def test_non_json_scalar_string_passes_through(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_board": "ok"}),
        )
        result = runner.invoke(
            app,
            [
                "board",
                "update",
                "--id",
                "42",
                "--attribute",
                "name",
                "--value",
                "Renamed",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed == "ok"


# --- set-permission ---


class TestBoardSetPermission:
    def test_sets_board_permission(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"set_board_permission": {"edit_permissions": "viewer", "failed_actions": []}}),
        )
        result = runner.invoke(
            app,
            ["board", "set-permission", "--id", "42", "--role", "viewer"],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed == {"edit_permissions": "viewer", "failed_actions": []}
        v = _last_body(httpx_mock)["variables"]
        assert v == {"board": 42, "role": "viewer"}


# --- move ---


class TestBoardMove:
    def test_moves_board_with_all_supported_fields(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_board_hierarchy": {"success": True}}),
        )
        result = runner.invoke(
            app,
            [
                "board",
                "move",
                "--id",
                "42",
                "--workspace",
                "7",
                "--folder",
                "8",
                "--product-id",
                "9",
                "--position",
                '{"object_id":15,"object_type":"Overview","is_after":true}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed == {"success": True}
        v = _last_body(httpx_mock)["variables"]
        assert v == {
            "board": 42,
            "attributes": {
                "workspace_id": 7,
                "folder_id": 8,
                "account_product_id": 9,
                "position": {
                    "object_id": 15,
                    "object_type": "Overview",
                    "is_after": True,
                },
            },
        }

    def test_requires_at_least_one_move_target(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["board", "move", "--id", "42"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_position_invalid_json(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["board", "move", "--id", "42", "--position", "{not json"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_invalidates_board_cache(
        self,
        httpx_mock: HTTPXMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mondo.cli import _list_decorate as list_decorate

        monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")
        monkeypatch.setattr(list_decorate, "enrich_workspaces_best_effort", lambda entries, opts: None)
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "1", "name": "Alpha"}]}),
        )
        list_result = runner.invoke(app, ["board", "list"])
        assert list_result.exit_code == 0, list_result.stdout
        cache_file = tmp_path / "cache" / "default" / "boards.json"
        assert cache_file.exists()

        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_board_hierarchy": {"success": True}}),
        )
        move_result = runner.invoke(app, ["board", "move", "--id", "42", "--workspace", "7"])
        assert move_result.exit_code == 0, move_result.stdout
        assert not cache_file.exists()


# --- archive ---


class TestBoardArchive:
    def test_archive_requires_yes_when_interactive(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["board", "archive", "--id", "42"], input="n\n")
        assert result.exit_code == 1
        assert "aborted" in result.stdout

    def test_archive_with_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"archive_board": {"id": "42", "state": "archived"}}),
        )
        result = runner.invoke(app, ["--yes", "board", "archive", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["state"] == "archived"


# --- delete ---


class TestBoardDelete:
    def test_delete_without_hard_exits_2(self) -> None:
        result = runner.invoke(app, ["--yes", "board", "delete", "--id", "42"])
        assert result.exit_code == 2
        assert "--hard" in result.stderr

    def test_delete_with_hard_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_board": {"id": "42", "state": "deleted"}}),
        )
        result = runner.invoke(
            app,
            ["--yes", "board", "delete", "--id", "42", "--hard"],
        )
        assert result.exit_code == 0, result.stdout


# --- duplicate ---


class TestBoardDuplicate:
    def test_default_type_resolves_source_workspace(self, httpx_mock: HTTPXMock) -> None:
        # No --workspace → CLI looks up the source board first, then duplicates
        # into the same workspace.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "workspace_id": "1999837"}]}),
        )
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_board": {"board": {"id": "100", "name": "Copy"}}}),
        )
        result = runner.invoke(app, ["board", "duplicate", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        bodies = _bodies(httpx_mock)
        assert len(bodies) == 2
        assert bodies[0]["variables"] == {"id": 42}
        v = bodies[1]["variables"]
        assert v["board"] == 42
        assert v["duplicateType"] == "duplicate_board_with_structure"
        assert v["workspace"] == 1999837

    def test_missing_source_board_errors(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": []}),
        )
        result = runner.invoke(app, ["board", "duplicate", "--id", "42"])
        assert result.exit_code == 1
        assert "source board 42 not found" in result.stderr

    def test_with_pulses_and_options(self, httpx_mock: HTTPXMock) -> None:
        # Explicit --workspace → no source lookup, only the mutation.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_board": {"board": {"id": "101"}}}),
        )
        result = runner.invoke(
            app,
            [
                "board",
                "duplicate",
                "--id",
                "42",
                "--type",
                "duplicate_board_with_pulses_and_updates",
                "--name",
                "Cloned",
                "--workspace",
                "7",
                "--keep-subscribers",
            ],
        )
        assert result.exit_code == 0, result.stdout
        bodies = _bodies(httpx_mock)
        assert len(bodies) == 1
        v = bodies[0]["variables"]
        assert v["duplicateType"] == "duplicate_board_with_pulses_and_updates"
        assert v["name"] == "Cloned"
        assert v["workspace"] == 7
        assert v["keepSubscribers"] is True

    def test_wait_envelope_for_structure_only(
        self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Structure-only duplicates target items_count=0 (because no items
        are copied). The `_wait` envelope must report `matched: true` and
        `expected: 0` so callers don't have to reason about the historical
        `source_items_count` mismatch."""
        # 1) duplicate_board mutation → returns the new board id
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_board": {"board": {"id": "101", "name": "Copy"}}}),
        )
        # Skip the polling loop entirely.
        from mondo.api import polling as _polling

        monkeypatch.setattr(_polling, "wait_for_items_count_stable", lambda *a, **k: 0)
        result = runner.invoke(
            app,
            [
                "board",
                "duplicate",
                "--id",
                "42",
                "--type",
                "duplicate_board_with_structure",
                "--workspace",
                "7",
                "--wait",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["_wait"] == {
            "final_items_count": 0,
            "expected": 0,
            "matched": True,
        }

    def test_output_normalizes_nested_board(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "duplicate_board": {
                        "board": {"id": "101", "name": "Copy", "board_kind": "private"}
                    }
                }
            ),
        )
        result = runner.invoke(app, ["board", "duplicate", "--id", "42", "--workspace", "7"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["board"]["kind"] == "private"
        assert "board_kind" not in parsed["board"]
