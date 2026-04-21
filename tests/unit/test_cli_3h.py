"""End-to-end CLI tests for Phase 3h: activity / folder / favorite / tag."""

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
    # Default to live (non-cache) path; cache-specific tests opt back in by
    # re-setting MONDO_CACHE_ENABLED=true.
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _last_body(httpx_mock: HTTPXMock) -> dict:
    return json.loads(httpx_mock.get_requests()[-1].content)


# --- activity ---


class TestActivity:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "boards": [
                        {
                            "id": "42",
                            "activity_logs": [
                                {
                                    "id": "a1",
                                    "event": "change_column_value",
                                    "user_id": "1",
                                },
                                {
                                    "id": "a2",
                                    "event": "create_item",
                                    "user_id": "1",
                                },
                            ],
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["activity", "board", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [log["id"] for log in parsed] == ["a1", "a2"]

    def test_filters(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"boards": [{"id": "42", "activity_logs": []}]}),
        )
        result = runner.invoke(
            app,
            [
                "activity",
                "board",
                "--board",
                "42",
                "--since",
                "2026-04-01T00:00:00Z",
                "--until",
                "2026-04-18T23:59:59Z",
                "--user",
                "1",
                "--user",
                "2",
                "--item",
                "100",
                "--group",
                "topics",
                "--column",
                "status",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["fromDate"] == "2026-04-01T00:00:00Z"
        assert v["toDate"] == "2026-04-18T23:59:59Z"
        assert v["userIds"] == [1, 2]
        assert v["itemIds"] == [100]
        assert v["groupIds"] == ["topics"]
        assert v["columnIds"] == ["status"]

    def test_board_not_found(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["activity", "board", "--board", "999"])
        assert result.exit_code == 6


# --- folder ---


class TestFolderList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "folders": [
                        {"id": "1", "name": "Eng"},
                        {"id": "2", "name": "Ops"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["folder", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [f["id"] for f in parsed] == ["1", "2"]

    def test_workspace_filter(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"folders": []}))
        result = runner.invoke(
            app,
            ["folder", "list", "--workspace", "42", "--workspace", "43"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["workspaceIds"] == [42, 43]


class TestFolderListCache:
    """Cache-backed `folder list` — enabled by re-setting MONDO_CACHE_ENABLED=true
    on top of the module-level `_clean_env` default (which disables cache)."""

    @pytest.fixture(autouse=True)
    def _enable_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")

    def _folder_response(self, folders: list[dict]) -> dict:
        """Wrap folders in an API-style ok envelope."""
        return _ok({"folders": folders})

    def _sample_folders(self) -> list[dict]:
        return [
            {
                "id": "1",
                "name": "Eng",
                "color": None,
                "created_at": "2024-01-01T00:00:00Z",
                "owner_id": "10",
                "workspace": {"id": "42", "name": "Main WS"},
                "parent": None,
            },
            {
                "id": "2",
                "name": "Ops",
                "color": "DONE_GREEN",
                "created_at": "2024-02-01T00:00:00Z",
                "owner_id": "10",
                "workspace": {"id": "43", "name": "Other WS"},
                "parent": {"id": "99", "name": "Root"},
            },
        ]

    def test_cold_then_warm_cache(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        """First call fetches from API and writes cache; second call is served from cache."""
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=self._folder_response(self._sample_folders())
        )
        first = runner.invoke(app, ["folder", "list"])
        assert first.exit_code == 0, first.stdout
        parsed = json.loads(first.stdout)
        assert sorted(f["id"] for f in parsed) == ["1", "2"]
        cache_file = tmp_path / "cache" / "default" / "folders.json"
        assert cache_file.exists()
        prime_requests = len(httpx_mock.get_requests())

        # Second call: no new response queued — must be served from cache.
        second = runner.invoke(app, ["folder", "list"])
        assert second.exit_code == 0, second.stdout
        assert sorted(f["id"] for f in json.loads(second.stdout)) == ["1", "2"]
        assert len(httpx_mock.get_requests()) == prime_requests

    def test_no_cache_bypasses(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        """--no-cache skips cache even when it's warm."""
        # Prime the cache.
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=self._folder_response(self._sample_folders())
        )
        runner.invoke(app, ["folder", "list"])
        assert (tmp_path / "cache" / "default" / "folders.json").exists()
        prime_requests = len(httpx_mock.get_requests())

        # --no-cache must hit the API again.
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=self._folder_response([])
        )
        result = runner.invoke(app, ["folder", "list", "--no-cache"])
        assert result.exit_code == 0, result.stdout
        assert len(httpx_mock.get_requests()) == prime_requests + 1

    def test_refresh_cache_forces_refetch(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        """--refresh-cache discards stale cache and re-fetches."""
        # Prime with stale content.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=self._folder_response([
                {
                    "id": "1",
                    "name": "Stale",
                    "color": None,
                    "created_at": None,
                    "owner_id": None,
                    "workspace": None,
                    "parent": None,
                }
            ]),
        )
        runner.invoke(app, ["folder", "list"])
        prime_requests = len(httpx_mock.get_requests())

        # Re-fetch with fresh content.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=self._folder_response([
                {
                    "id": "9",
                    "name": "Fresh",
                    "color": None,
                    "created_at": None,
                    "owner_id": None,
                    "workspace": None,
                    "parent": None,
                }
            ]),
        )
        result = runner.invoke(app, ["folder", "list", "--refresh-cache"])
        assert result.exit_code == 0, result.stdout
        assert json.loads(result.stdout)[0]["name"] == "Fresh"
        assert len(httpx_mock.get_requests()) == prime_requests + 1

    def test_no_cache_and_refresh_cache_mutually_exclusive(self) -> None:
        result = runner.invoke(
            app, ["folder", "list", "--no-cache", "--refresh-cache"]
        )
        assert result.exit_code == 2
        assert "mutually exclusive" in (result.stderr or result.stdout).lower()

    def test_workspace_filter_applies_client_side(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """--workspace filters cache entries client-side without a new API call."""
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=self._folder_response(self._sample_folders())
        )
        result = runner.invoke(app, ["folder", "list", "--workspace", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [f["id"] for f in parsed] == ["1"]

    def test_workspace_filter_type_coercion(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """workspace_id stored as string in cache still matches int --workspace arg."""
        # normalize_folder_entry stores workspace_id as the raw value from GraphQL
        # (a string like "42"). The --workspace flag is int. Both are compared as
        # strings, so "42" == str(42) == "42". This test verifies that.
        folders_with_string_ws_id = [
            {
                "id": "10",
                "name": "StringWS",
                "color": None,
                "created_at": None,
                "owner_id": None,
                "workspace": {"id": "99", "name": "WS 99"},
                "parent": None,
            }
        ]
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=self._folder_response(folders_with_string_ws_id),
        )
        result = runner.invoke(app, ["folder", "list", "--workspace", "99"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [f["id"] for f in parsed] == ["10"]

    def test_max_items_truncates_cache_results(
        self, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=self._folder_response(self._sample_folders())
        )
        result = runner.invoke(app, ["folder", "list", "--max-items", "1"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert len(parsed) == 1

    def test_emitted_entries_have_flat_columns(
        self, httpx_mock: HTTPXMock
    ) -> None:
        """Entries must have flat workspace_id/name and parent_id/name, not nested dicts."""
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=self._folder_response(self._sample_folders())
        )
        result = runner.invoke(app, ["folder", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        folder2 = next(f for f in parsed if f["id"] == "2")
        assert folder2["workspace_id"] == "43"
        assert folder2["workspace_name"] == "Other WS"
        assert folder2["parent_id"] == "99"
        assert folder2["parent_name"] == "Root"
        assert "workspace" not in folder2
        assert "parent" not in folder2


class TestFolderTree:
    """Tests for `folder tree` subcommand."""

    def _folder_response(self, folders: list[dict]) -> dict:
        return _ok({"folders": folders})

    def _two_workspace_folders(self) -> list[dict]:
        """Two workspaces; Main WS has a nested sub-folder."""
        return [
            {
                "id": "42",
                "name": "Marketing",
                "color": None,
                "created_at": "2024-01-01T00:00:00Z",
                "owner_id": "10",
                "workspace": {"id": "999", "name": "Main Workspace"},
                "parent": None,
            },
            {
                "id": "44",
                "name": "Campaigns",
                "color": None,
                "created_at": "2024-01-02T00:00:00Z",
                "owner_id": "10",
                "workspace": {"id": "999", "name": "Main Workspace"},
                "parent": {"id": "42", "name": "Marketing"},
            },
            {
                "id": "43",
                "name": "Design",
                "color": None,
                "created_at": "2024-01-03T00:00:00Z",
                "owner_id": "10",
                "workspace": {"id": "999", "name": "Main Workspace"},
                "parent": None,
            },
            {
                "id": "50",
                "name": "Backend",
                "color": "DONE_GREEN",
                "created_at": "2024-02-01T00:00:00Z",
                "owner_id": "11",
                "workspace": {"id": "888", "name": "Dev Workspace"},
                "parent": None,
            },
        ]

    def test_tree_two_workspaces(self, httpx_mock: HTTPXMock) -> None:
        """Tree with two workspaces; Main WS has a nested sub-folder."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=self._folder_response(self._two_workspace_folders()),
        )
        result = runner.invoke(app, ["--output", "table", "folder", "tree"])
        assert result.exit_code == 0, result.stdout
        output = result.stdout
        assert "Main Workspace" in output
        assert "Dev Workspace" in output
        assert "[42] Marketing" in output
        assert "[44] Campaigns" in output
        assert "[43] Design" in output
        assert "[50] Backend" in output
        # Campaigns should be indented under Marketing
        lines = output.splitlines()
        marketing_idx = next(i for i, l in enumerate(lines) if "[42] Marketing" in l)
        campaigns_idx = next(i for i, l in enumerate(lines) if "[44] Campaigns" in l)
        assert campaigns_idx > marketing_idx

    def test_tree_workspace_filter(self, httpx_mock: HTTPXMock) -> None:
        """--workspace restricts output to the given workspace."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=self._folder_response(self._two_workspace_folders()),
        )
        result = runner.invoke(app, ["--output", "table", "folder", "tree", "--workspace", "888"])
        assert result.exit_code == 0, result.stdout
        output = result.stdout
        assert "Dev Workspace" in output
        assert "[50] Backend" in output
        assert "Main Workspace" not in output
        assert "[42] Marketing" not in output

    def test_tree_no_cache_forces_live_fetch(self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
        """--no-cache bypasses cache and hits the API directly."""
        monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")
        # Prime the cache with first response.
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=self._folder_response(self._two_workspace_folders())
        )
        runner.invoke(app, ["folder", "list"])
        prime_requests = len(httpx_mock.get_requests())

        # --no-cache must issue a new API request.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=self._folder_response([
                {
                    "id": "99",
                    "name": "Live Only",
                    "color": None,
                    "created_at": None,
                    "owner_id": None,
                    "workspace": {"id": "1", "name": "WS1"},
                    "parent": None,
                }
            ]),
        )
        result = runner.invoke(app, ["--output", "table", "folder", "tree", "--no-cache"])
        assert result.exit_code == 0, result.stdout
        assert len(httpx_mock.get_requests()) == prime_requests + 1
        assert "Live Only" in result.stdout

    def test_tree_json_output_structured(self, httpx_mock: HTTPXMock) -> None:
        """JSON output returns a structured nested list."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=self._folder_response(self._two_workspace_folders()),
        )
        result = runner.invoke(app, ["-o", "json", "folder", "tree"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, list)
        # Find the Main Workspace entry
        main_ws = next(e for e in parsed if e["workspace_id"] == "999")
        assert main_ws["workspace_name"] == "Main Workspace"
        top_level_ids = [f["id"] for f in main_ws["folders"]]
        assert "42" in top_level_ids
        assert "43" in top_level_ids
        # Campaigns must be nested under Marketing
        marketing = next(f for f in main_ws["folders"] if f["id"] == "42")
        assert len(marketing["sub_folders"]) == 1
        assert marketing["sub_folders"][0]["id"] == "44"
        # Dev Workspace
        dev_ws = next(e for e in parsed if e["workspace_id"] == "888")
        assert len(dev_ws["folders"]) == 1
        assert dev_ws["folders"][0]["id"] == "50"
        assert dev_ws["folders"][0]["sub_folders"] == []

    def test_tree_empty_folders(self, httpx_mock: HTTPXMock) -> None:
        """Empty folder list → empty string (table) or [] (JSON)."""
        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=self._folder_response([])
        )
        result_table = runner.invoke(app, ["--output", "table", "folder", "tree"])
        assert result_table.exit_code == 0, result_table.stdout

        httpx_mock.add_response(
            url=ENDPOINT, method="POST", json=self._folder_response([])
        )
        result_json = runner.invoke(app, ["-o", "json", "folder", "tree"])
        assert result_json.exit_code == 0, result_json.stdout
        assert json.loads(result_json.stdout) == []

    def test_dry_run_no_http_request(self, httpx_mock: HTTPXMock) -> None:
        """--dry-run emits a plan dict and exits 0 without making any HTTP request."""
        result = runner.invoke(app, ["--dry-run", "folder", "tree"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict)


class TestFolderGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"folders": [{"id": "7", "name": "Eng"}]}),
        )
        result = runner.invoke(app, ["folder", "get", "--id", "7"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Eng"

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"folders": []}))
        result = runner.invoke(app, ["folder", "get", "--id", "999"])
        assert result.exit_code == 6


class TestFolderCreate:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_folder": {"id": "7", "name": "New"}}),
        )
        result = runner.invoke(
            app,
            [
                "folder",
                "create",
                "--name",
                "New",
                "--workspace",
                "42",
                "--color",
                "DONE_GREEN",
                "--parent",
                "3",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["name"] == "New"
        assert v["workspace"] == 42
        assert v["color"] == "DONE_GREEN"
        assert v["parent"] == 3


class TestFolderUpdate:
    def test_requires_at_least_one_attr(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["folder", "update", "--id", "7"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_name_only(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_folder": {"id": "7", "name": "Renamed"}}),
        )
        result = runner.invoke(app, ["folder", "update", "--id", "7", "--name", "Renamed"])
        assert result.exit_code == 0, result.stdout

    def test_position_json(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_folder": {"id": "7"}}),
        )
        result = runner.invoke(
            app,
            [
                "folder",
                "update",
                "--id",
                "7",
                "--position",
                '{"object_id":8,"object_type":"Folder","is_after":true}',
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["position"] == {
            "object_id": 8,
            "object_type": "Folder",
            "is_after": True,
        }

    def test_position_invalid_json(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["folder", "update", "--id", "7", "--position", "{not json"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


class TestFolderDelete:
    def test_without_hard_exits_2(self) -> None:
        result = runner.invoke(app, ["--yes", "folder", "delete", "--id", "7"])
        assert result.exit_code == 2

    def test_hard_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_folder": {"id": "7", "name": "Eng"}}),
        )
        result = runner.invoke(app, ["--yes", "folder", "delete", "--id", "7", "--hard"])
        assert result.exit_code == 0, result.stdout


# --- favorite ---


class TestFavoriteList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "favorites": [
                        {"id": "1", "type": "BOARD", "entity_id": "42"},
                        {"id": "2", "type": "DOC", "entity_id": "99"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["favorite", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [f["id"] for f in parsed] == ["1", "2"]

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["--dry-run", "favorite", "list"])
        assert result.exit_code == 0, result.stdout
        assert httpx_mock.get_requests() == []


# --- tag ---


class TestTag:
    def test_list(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "tags": [
                        {"id": "1", "name": "urgent", "color": "red"},
                        {"id": "2", "name": "blocked", "color": "yellow"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["tag", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [t["name"] for t in parsed] == ["urgent", "blocked"]

    def test_list_filter(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"tags": []}))
        result = runner.invoke(app, ["tag", "list", "--id", "1", "--id", "2"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"ids": [1, 2]}

    def test_get(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"tags": [{"id": "1", "name": "urgent"}]}),
        )
        result = runner.invoke(app, ["tag", "get", "--id", "1"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["id"] == "1"

    def test_get_missing_exit_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"tags": []}))
        result = runner.invoke(app, ["tag", "get", "--id", "999"])
        assert result.exit_code == 6

    def test_create_or_get(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_or_get_tag": {"id": "3", "name": "new"}}),
        )
        result = runner.invoke(
            app,
            ["tag", "create-or-get", "--name", "new", "--board", "42"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"name": "new", "board": 42}
