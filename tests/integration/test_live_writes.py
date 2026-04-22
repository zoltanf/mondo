"""Live Monday integration test covering real write operations.

This test is intentionally env-gated and marked `integration` because it
creates and deletes real resources in a playground workspace.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mondo.cli.main import app

MONDAY_TEST_TOKEN_ENV = "MONDAY_TEST_TOKEN"
MONDAY_TEST_WORKSPACE_ID_ENV = "MONDAY_TEST_WORKSPACE_ID"
DEFAULT_PLAYGROUND_WORKSPACE_ID = 592446
API_VERSION = "2026-01"

runner = CliRunner()


def _require_live_token() -> str:
    token = os.environ.get(MONDAY_TEST_TOKEN_ENV)
    if not token:
        pytest.skip(f"set {MONDAY_TEST_TOKEN_ENV} to run live Monday integration tests")
    return token


def _format_failure(args: list[str], result: Any) -> str:
    return (
        f"mondo {' '.join(args)}\n"
        f"exit_code={result.exit_code}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _invoke(args: list[str], *, expect_exit: int | None = 0) -> Any:
    result = runner.invoke(app, ["--yes", "--output", "json", *args])
    if expect_exit is not None:
        assert result.exit_code == expect_exit, _format_failure(args, result)
    return result


def _json_output(result: Any) -> Any:
    text = result.stdout.strip()
    assert text, "command produced no JSON output"
    return json.loads(text)


def _invoke_json(args: list[str], *, expect_exit: int | None = 0) -> Any:
    return _json_output(_invoke(args, expect_exit=expect_exit))


def _wait_for(
    description: str,
    probe: Any,
    *,
    timeout_seconds: float = 45.0,
    interval_seconds: float = 1.0,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_error: AssertionError | None = None
    while time.monotonic() < deadline:
        try:
            return probe()
        except AssertionError as exc:
            last_error = exc
            time.sleep(interval_seconds)
    detail = f": {last_error}" if last_error else ""
    raise AssertionError(f"timed out waiting for {description}{detail}")


@dataclass
class CleanupAction:
    label: str
    args: list[str]


@dataclass
class CleanupPlan:
    actions: list[CleanupAction] = field(default_factory=list)

    def add(self, label: str, *args: str) -> None:
        self.actions.append(CleanupAction(label=label, args=list(args)))


@pytest.fixture
def live_workspace_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> int:
    token = _require_live_token()
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", token)
    monkeypatch.setenv("MONDAY_API_VERSION", API_VERSION)
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")
    return int(os.environ.get(MONDAY_TEST_WORKSPACE_ID_ENV, DEFAULT_PLAYGROUND_WORKSPACE_ID))


@pytest.fixture
def cleanup_plan(live_workspace_id: int) -> CleanupPlan:
    plan = CleanupPlan()
    yield plan

    failures: list[str] = []
    for action in reversed(plan.actions):
        deadline = time.monotonic() + 45.0
        while True:
            result = _invoke(action.args, expect_exit=None)
            if result.exit_code in {0, 6}:
                break
            if time.monotonic() >= deadline:
                failures.append(f"{action.label} cleanup failed\n{_format_failure(action.args, result)}")
                break
            time.sleep(1.0)
    if failures:
        pytest.fail("\n\n".join(failures))


def _probe_board(board_id: int, *, workspace_id: int, folder_id: int, board_name: str) -> dict[str, Any]:
    result = _invoke(["board", "get", "--id", str(board_id)], expect_exit=None)
    assert result.exit_code == 0, _format_failure(["board", "get", "--id", str(board_id)], result)
    board = _json_output(result)
    assert board["name"] == board_name
    assert str(board["workspace_id"]) == str(workspace_id)
    assert str(board["folder_id"]) == str(folder_id)
    return board


def _probe_group(board_id: int, group_id: str, group_name: str) -> list[dict[str, Any]]:
    result = _invoke(["group", "list", "--board", str(board_id)], expect_exit=None)
    assert result.exit_code == 0, _format_failure(["group", "list", "--board", str(board_id)], result)
    groups = _json_output(result)
    match = next((group for group in groups if group["id"] == group_id), None)
    assert match is not None, f"group {group_id} not visible on board {board_id}"
    assert match["title"] == group_name
    return groups


def _probe_columns(board_id: int, expected: dict[str, str]) -> list[dict[str, Any]]:
    result = _invoke(["column", "list", "--board", str(board_id)], expect_exit=None)
    assert result.exit_code == 0, _format_failure(["column", "list", "--board", str(board_id)], result)
    columns = _json_output(result)
    by_id = {column["id"]: column for column in columns}
    for column_id, column_type in expected.items():
        assert column_id in by_id, f"column {column_id!r} not visible on board {board_id}"
        assert by_id[column_id]["type"] == column_type
    return columns


def _probe_item(
    item_id: int,
    *,
    board_id: int,
    group_id: str,
    item_name: str,
    expected_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = _invoke(["item", "get", "--id", str(item_id)], expect_exit=None)
    assert result.exit_code == 0, _format_failure(["item", "get", "--id", str(item_id)], result)
    item = _json_output(result)
    assert item["name"] == item_name
    assert str(item["board"]["id"]) == str(board_id)
    assert item["group"]["id"] == group_id
    if expected_texts:
        values = {value["id"]: value for value in item.get("column_values") or []}
        for column_id, expected_text in expected_texts.items():
            assert values[column_id]["text"] == expected_text
    return item


@pytest.mark.integration
def test_live_cli_writes_folder_board_group_columns_and_item(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    suffix = uuid.uuid4().hex[:8]
    folder_name = f"e2e mondo test {suffix}"
    board_name = f"E2E Mondo Board {suffix}"
    group_name = f"E2E Group {suffix}"
    item_name = f"E2E Item {suffix}"
    text_value = f"text value {suffix}"
    note_value = f"note value {suffix}"

    folder = _invoke_json(
        [
            "folder",
            "create",
            "--workspace",
            str(live_workspace_id),
            "--name",
            folder_name,
        ]
    )
    folder_id = int(folder["id"])
    cleanup_plan.add("folder", "folder", "delete", "--id", str(folder_id), "--hard")

    board = _invoke_json(
        [
            "board",
            "create",
            "--workspace",
            str(live_workspace_id),
            "--folder",
            str(folder_id),
            "--name",
            board_name,
            "--kind",
            "private",
            "--empty",
        ]
    )
    board_id = int(board["id"])
    cleanup_plan.add("board", "board", "delete", "--id", str(board_id), "--hard")

    _wait_for(
        "board creation",
        lambda: _probe_board(
            board_id,
            workspace_id=live_workspace_id,
            folder_id=folder_id,
            board_name=board_name,
        ),
    )

    group = _invoke_json(
        [
            "group",
            "create",
            "--board",
            str(board_id),
            "--name",
            group_name,
        ]
    )
    group_id = group["id"]
    _wait_for("group creation", lambda: _probe_group(board_id, group_id, group_name))

    text_column = _invoke_json(
        [
            "column",
            "create",
            "--board",
            str(board_id),
            "--title",
            "E2E Text",
            "--type",
            "text",
            "--id",
            "e2e_text",
        ]
    )
    assert text_column["id"] == "e2e_text"
    assert text_column["type"] == "text"

    note_column = _invoke_json(
        [
            "column",
            "create",
            "--board",
            str(board_id),
            "--title",
            "E2E Note",
            "--type",
            "long_text",
            "--id",
            "e2e_note",
        ]
    )
    assert note_column["id"] == "e2e_note"
    assert note_column["type"] == "long_text"

    _wait_for(
        "column creation",
        lambda: _probe_columns(board_id, {"e2e_text": "text", "e2e_note": "long_text"}),
    )

    item = _invoke_json(
        [
            "item",
            "create",
            "--board",
            str(board_id),
            "--group",
            group_id,
            "--name",
            item_name,
        ]
    )
    item_id = int(item["id"])
    cleanup_plan.add("item", "item", "delete", "--id", str(item_id), "--hard")

    _wait_for(
        "item creation",
        lambda: _probe_item(item_id, board_id=board_id, group_id=group_id, item_name=item_name),
    )

    _invoke_json(
        [
            "column",
            "set",
            "--item",
            str(item_id),
            "--column",
            "e2e_text",
            "--value",
            text_value,
        ]
    )
    _invoke_json(
        [
            "column",
            "set",
            "--item",
            str(item_id),
            "--column",
            "e2e_note",
            "--value",
            note_value,
        ]
    )

    _wait_for(
        "column value writes",
        lambda: _probe_item(
            item_id,
            board_id=board_id,
            group_id=group_id,
            item_name=item_name,
            expected_texts={"e2e_text": text_value, "e2e_note": note_value},
        ),
    )

    rendered_text = _invoke_json(
        ["column", "get", "--item", str(item_id), "--column", "e2e_text"]
    )
    assert rendered_text == text_value

    rendered_note = _invoke_json(
        ["column", "get", "--item", str(item_id), "--column", "e2e_note"]
    )
    assert rendered_note == note_value
