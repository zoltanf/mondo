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

    def test_items_count_omitted_by_default(self, httpx_mock: HTTPXMock) -> None:
        """items_count costs ~500k complexity per page; opt-in only."""
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["board", "list"])
        assert result.exit_code == 0, result.stdout
        assert "items_count" not in _last_body(httpx_mock)["query"]

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
            ["--dry-run", "board", "create", "--name", "X", "--kind", "public"],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "create_board" in parsed["query"]
        assert parsed["variables"]["name"] == "X"
        assert httpx_mock.get_requests() == []


# --- update ---


class TestBoardUpdate:
    def test_change_name(self, httpx_mock: HTTPXMock) -> None:
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
        v = _last_body(httpx_mock)["variables"]
        assert v == {"board": 42, "attribute": "name", "value": "Renamed"}


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
