"""End-to-end CLI tests for the `mondo group ...` command group."""

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
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _last_body(httpx_mock: HTTPXMock) -> dict:
    return json.loads(httpx_mock.get_requests()[-1].content)


def _groups_ok(*groups: dict[str, object]) -> dict:
    return _ok({"boards": [{"id": "42", "name": "B", "groups": list(groups)}]})


def _groups_cache_path(tmp_path: Path, board_id: int = 42) -> Path:
    return tmp_path / "cache" / "default" / "groups" / f"{board_id}.json"


# --- list ---


class TestGroupList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_groups_ok(
                {"id": "topics", "title": "Topics"},
                {"id": "new_group", "title": "New"},
            ),
        )
        result = runner.invoke(app, ["group", "list", "--board", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [g["id"] for g in parsed] == ["topics", "new_group"]

    def test_list_writes_cache_then_warm_hit(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_groups_ok({"id": "topics", "title": "Topics"}),
        )
        first = runner.invoke(app, ["group", "list", "--board", "42"])
        assert first.exit_code == 0, first.stdout
        assert _groups_cache_path(tmp_path).exists()

        # No second response registered. A warm-cache hit should still succeed.
        second = runner.invoke(app, ["group", "list", "--board", "42"])
        assert second.exit_code == 0, second.stdout

    def test_no_cache_bypasses_cache_and_does_not_write(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_groups_ok({"id": "topics", "title": "Topics"}),
        )
        result = runner.invoke(app, ["group", "list", "--board", "42", "--no-cache"])
        assert result.exit_code == 0, result.stdout
        assert not _groups_cache_path(tmp_path).exists()

    def test_refresh_cache_forces_refetch(
        self, httpx_mock: HTTPXMock, tmp_path: Path
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_groups_ok({"id": "stale", "title": "Stale"}),
        )
        warm = runner.invoke(app, ["group", "list", "--board", "42"])
        assert warm.exit_code == 0, warm.stdout
        assert _groups_cache_path(tmp_path).exists()

        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_groups_ok({"id": "fresh", "title": "Fresh"}),
        )
        refreshed = runner.invoke(app, ["group", "list", "--board", "42", "--refresh-cache"])
        assert refreshed.exit_code == 0, refreshed.stdout
        parsed = json.loads(refreshed.stdout)
        assert [g["id"] for g in parsed] == ["fresh"]

    def test_no_cache_plus_refresh_cache_rejected(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app, ["group", "list", "--board", "42", "--no-cache", "--refresh-cache"]
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_board_not_found_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"boards": []}))
        result = runner.invoke(app, ["group", "list", "--board", "999"])
        assert result.exit_code == 6


# --- create ---


class TestGroupCreate:
    def test_minimal(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_group": {"id": "new_group_1", "title": "Planning"}}),
        )
        result = runner.invoke(
            app,
            ["group", "create", "--board", "42", "--name", "Planning"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["name"] == "Planning"
        assert v["color"] is None

    def test_with_valid_color(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_group": {"id": "g1"}}),
        )
        result = runner.invoke(
            app,
            [
                "group",
                "create",
                "--board",
                "42",
                "--name",
                "Pink",
                "--color",
                "#ff007f",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["color"] == "#ff007f"

    def test_color_without_hash_normalized(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_group": {"id": "g1"}}),
        )
        result = runner.invoke(
            app,
            [
                "group",
                "create",
                "--board",
                "42",
                "--name",
                "X",
                "--color",
                "00c875",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["color"] == "#00c875"

    def test_invalid_color_exits_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "group",
                "create",
                "--board",
                "42",
                "--name",
                "X",
                "--color",
                "#deadbeef",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_relative_to_with_prm(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"create_group": {"id": "g1"}}),
        )
        result = runner.invoke(
            app,
            [
                "group",
                "create",
                "--board",
                "42",
                "--name",
                "X",
                "--relative-to",
                "topics",
                "--position-relative-method",
                "after_at",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["relativeTo"] == "topics"
        assert v["prm"] == "after_at"


# --- rename / update / reorder ---


class TestGroupRename:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_group": {"id": "topics", "title": "New"}}),
        )
        result = runner.invoke(
            app,
            ["group", "rename", "--board", "42", "--id", "topics", "--title", "New"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {
            "board": 42,
            "group": "topics",
            "attribute": "title",
            "value": "New",
        }


class TestGroupUpdate:
    def test_color_value_passes_through_unchanged(self, httpx_mock: HTTPXMock) -> None:
        """Monday's `update_group` mutation wants color NAMES ('green'), not
        hex codes — divergent from `create_group`/`rename_group` which take
        hex. The CLI passes the user's value through unchanged; the server
        does the validation."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_group": {"id": "topics", "color": "#00c875"}}),
        )
        result = runner.invoke(
            app,
            [
                "group",
                "update",
                "--board",
                "42",
                "--id",
                "topics",
                "--attribute",
                "color",
                "--value",
                "green",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["attribute"] == "color"
        assert v["value"] == "green"

    def test_color_hex_also_passes_through(self, httpx_mock: HTTPXMock) -> None:
        """Even if the user passes hex (invalid for update_group), the CLI
        does NOT reject client-side anymore — we let monday respond so the
        user sees the authoritative error. Previously we rejected hex that
        wasn't in the palette, which is wrong for update_group."""
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_group": {"id": "topics"}}),
        )
        result = runner.invoke(
            app,
            [
                "group",
                "update",
                "--board",
                "42",
                "--id",
                "topics",
                "--attribute",
                "color",
                "--value",
                "#00c875",
            ],
        )
        # No client-side rejection — the request actually goes out
        assert result.exit_code == 0, result.stdout
        assert len(httpx_mock.get_requests()) == 1


class TestGroupReorder:
    def test_after(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_group": {"id": "x"}}),
        )
        result = runner.invoke(
            app,
            ["group", "reorder", "--board", "42", "--id", "x", "--after", "topics"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["attribute"] == "relative_position_after"
        assert v["value"] == "topics"

    def test_before(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_group": {"id": "x"}}),
        )
        result = runner.invoke(
            app,
            ["group", "reorder", "--board", "42", "--id", "x", "--before", "topics"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["attribute"] == "relative_position_before"

    def test_position(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"update_group": {"id": "x"}}),
        )
        result = runner.invoke(
            app,
            ["group", "reorder", "--board", "42", "--id", "x", "--position", "3"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["attribute"] == "position"
        assert v["value"] == "3"

    def test_missing_required_flags(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["group", "reorder", "--board", "42", "--id", "x"])
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []

    def test_multiple_flags_exit_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "group",
                "reorder",
                "--board",
                "42",
                "--id",
                "x",
                "--after",
                "a",
                "--before",
                "b",
            ],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


# --- duplicate ---


class TestGroupDuplicate:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_group": {"id": "g_dup", "title": "Copy"}}),
        )
        result = runner.invoke(
            app,
            ["group", "duplicate", "--board", "42", "--id", "topics", "--title", "Copy"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["title"] == "Copy"

    def test_add_to_top(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"duplicate_group": {"id": "g_dup"}}),
        )
        result = runner.invoke(
            app,
            [
                "group",
                "duplicate",
                "--board",
                "42",
                "--id",
                "topics",
                "--add-to-top",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["addToTop"] is True


# --- archive ---


class TestGroupArchive:
    def test_requires_confirm(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["group", "archive", "--board", "42", "--id", "topics"],
            input="n\n",
        )
        assert result.exit_code == 1

    def test_yes_skips_prompt(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"archive_group": {"id": "topics", "archived": True}}),
        )
        result = runner.invoke(
            app,
            ["--yes", "group", "archive", "--board", "42", "--id", "topics"],
        )
        assert result.exit_code == 0, result.stdout


# --- delete ---


class TestGroupDelete:
    def test_without_hard_exits_2(self) -> None:
        result = runner.invoke(
            app,
            ["--yes", "group", "delete", "--board", "42", "--id", "topics"],
        )
        assert result.exit_code == 2
        assert "--hard" in result.stderr

    def test_hard_and_yes(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"delete_group": {"id": "topics", "deleted": True}}),
        )
        result = runner.invoke(
            app,
            ["--yes", "group", "delete", "--board", "42", "--id", "topics", "--hard"],
        )
        assert result.exit_code == 0, result.stdout

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            [
                "--yes",
                "--dry-run",
                "group",
                "delete",
                "--board",
                "42",
                "--id",
                "topics",
                "--hard",
            ],
        )
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert "delete_group" in parsed["query"]
        assert httpx_mock.get_requests() == []


class TestGroupMutationInvalidation:
    @pytest.mark.parametrize(
        ("argv", "payload"),
        [
            (
                ["group", "create", "--board", "42", "--name", "Planning"],
                _ok({"create_group": {"id": "g1"}}),
            ),
            (
                ["group", "rename", "--board", "42", "--id", "topics", "--title", "Renamed"],
                _ok({"update_group": {"id": "topics", "title": "Renamed"}}),
            ),
            (
                [
                    "group",
                    "update",
                    "--board",
                    "42",
                    "--id",
                    "topics",
                    "--attribute",
                    "position",
                    "--value",
                    "2",
                ],
                _ok({"update_group": {"id": "topics"}}),
            ),
            (
                ["group", "reorder", "--board", "42", "--id", "topics", "--after", "done"],
                _ok({"update_group": {"id": "topics"}}),
            ),
            (
                ["group", "duplicate", "--board", "42", "--id", "topics"],
                _ok({"duplicate_group": {"id": "topics_copy"}}),
            ),
            (
                ["--yes", "group", "archive", "--board", "42", "--id", "topics"],
                _ok({"archive_group": {"id": "topics", "archived": True}}),
            ),
            (
                ["--yes", "group", "delete", "--board", "42", "--id", "topics", "--hard"],
                _ok({"delete_group": {"id": "topics", "deleted": True}}),
            ),
        ],
    )
    def test_successful_group_mutations_invalidate_groups_cache(
        self,
        httpx_mock: HTTPXMock,
        tmp_path: Path,
        argv: list[str],
        payload: dict,
    ) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_groups_ok({"id": "topics", "title": "Topics"}),
        )
        warm = runner.invoke(app, ["group", "list", "--board", "42"])
        assert warm.exit_code == 0, warm.stdout
        cache_file = _groups_cache_path(tmp_path)
        assert cache_file.exists()

        httpx_mock.add_response(url=ENDPOINT, method="POST", json=payload)
        result = runner.invoke(app, argv)
        assert result.exit_code == 0, result.stdout
        assert not cache_file.exists()
