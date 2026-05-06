"""Shared fixtures and `.env` loader for the live integration suite.

`.env` is loaded with `override=False` so existing shell env values still
win — keeps CI/explicit invocations safe. The conftest is scoped to
`tests/integration/` only, so unit tests never see the live token.

Function-scoped fixtures (`live_workspace_id`, `cleanup_plan`,
`live_test_board_id`, `live_test_doc_id`) cover one-off tests that build
their own resources. The session-scoped `pm_board_session` fixture builds
a realistic project-management board once per pytest session for the
read-heavy tests under tests/integration/test_live_pm_board.py and
sibling files.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest
from dotenv import load_dotenv

from ._helpers import (
    API_VERSION,
    CleanupPlan,
    MONDO_TEST_BOARD_ID_ENV,
    MONDO_TEST_DOC_ID_ENV,
    invoke,
    invoke_json,
    playground_workspace_id,
    require_live_token,
    run_cleanup,
    wait_for,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=False)


# ---------------------------------------------------------------------------
# Function-scoped fixtures (existing — moved from test_live_writes.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def live_workspace_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> int:
    """Function-scoped env setup + playground workspace id.

    Sets MONDAY_API_TOKEN/VERSION, disables config + cache, returns the
    playground workspace id (env-driven, fallback to the constant).
    """
    token = require_live_token()
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", token)
    monkeypatch.setenv("MONDAY_API_VERSION", API_VERSION)
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")
    return playground_workspace_id()


@pytest.fixture
def cleanup_plan(live_workspace_id: int) -> Iterator[CleanupPlan]:
    """Function-scoped LIFO cleanup. Yields a `CleanupPlan` and runs it on teardown."""
    del live_workspace_id  # ensure env is set up before tests register cleanup
    plan = CleanupPlan()
    yield plan
    run_cleanup(plan)


@pytest.fixture
def live_test_board_id(live_workspace_id: int) -> int:
    """Existing long-lived playground board id, gated by MONDO_TEST_BOARD_ID."""
    raw = os.environ.get(MONDO_TEST_BOARD_ID_ENV)
    if not raw:
        pytest.skip(f"set {MONDO_TEST_BOARD_ID_ENV} to run feature-coverage live tests")
    del live_workspace_id  # consumed only for token gate + monkeypatch setup
    return int(raw)


@pytest.fixture
def live_test_doc_id(live_workspace_id: int) -> int:
    """Pre-prepared doc id (the one with notice boxes), gated by MONDO_TEST_DOC_ID."""
    raw = os.environ.get(MONDO_TEST_DOC_ID_ENV)
    if not raw:
        pytest.skip(f"set {MONDO_TEST_DOC_ID_ENV} to run doc read tests")
    del live_workspace_id
    return int(raw)


# ---------------------------------------------------------------------------
# Session-scoped PM board fixture
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PmBoard:
    """Description of the session-scoped project-management board.

    Built fresh per pytest session by `pm_board_session`; torn down at
    session end via `session_cleanup_plan`. Read-heavy tests reuse it
    via `pm_board_session`; tests that mutate items create scratch items
    on the same board with their own (function-scoped) cleanup plans.
    """

    workspace_id: int
    folder_id: int
    board_id: int
    column_ids: dict[str, str]  # logical name -> column id (e.g. "status" -> "status_e2e")
    group_ids: dict[str, str]  # logical name -> group id (e.g. "backlog" -> "topics")
    item_ids: list[int]  # 5 fixture items, position-stable
    item_names: list[str]


@pytest.fixture(scope="session")
def session_env() -> Iterator[int]:
    """Session-scoped env setup. Returns playground workspace id."""
    token = require_live_token()
    mp = pytest.MonkeyPatch()
    cache_dir = Path(os.environ.get("PYTEST_TMP_DIR", "/tmp")) / f"mondo-session-{uuid.uuid4().hex[:8]}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    mp.delenv("MONDO_PROFILE", raising=False)
    mp.setenv("MONDO_CONFIG", str(cache_dir / "nope.yaml"))
    mp.setenv("MONDAY_API_TOKEN", token)
    mp.setenv("MONDAY_API_VERSION", API_VERSION)
    mp.setenv("MONDO_CACHE_DIR", str(cache_dir / "cache"))
    mp.setenv("MONDO_CACHE_ENABLED", "false")
    try:
        yield playground_workspace_id()
    finally:
        mp.undo()


@pytest.fixture(scope="session")
def session_cleanup_plan(session_env: int) -> Iterator[CleanupPlan]:
    """Session-scoped LIFO cleanup queue."""
    del session_env
    plan = CleanupPlan()
    yield plan
    run_cleanup(plan)


@pytest.fixture(scope="session")
def pm_board_session(
    session_env: int, session_cleanup_plan: CleanupPlan
) -> PmBoard:
    """Build a realistic PM board once per session.

    Layout: folder -> board with status / person / date / timeline / numbers
    / text / long_text / doc columns; 3 groups (Backlog/In Progress/Done);
    5 items distributed across them with column values populated.
    """
    workspace_id = session_env
    suffix = uuid.uuid4().hex[:8]

    # 1. Folder
    folder = invoke_json(
        [
            "folder", "create",
            "--workspace", str(workspace_id),
            "--name", f"E2E PM Session {suffix}",
        ]
    )
    folder_id = int(folder["id"])
    session_cleanup_plan.add(
        f"pm folder {folder_id}", "folder", "delete", "--id", str(folder_id), "--hard",
    )

    # 2. Board
    board = invoke_json(
        [
            "board", "create",
            "--workspace", str(workspace_id),
            "--folder", str(folder_id),
            "--name", f"E2E PM Board {suffix}",
            "--kind", "private",
            "--empty",
        ]
    )
    board_id = int(board["id"])
    session_cleanup_plan.add(
        f"pm board {board_id}", "board", "delete", "--id", str(board_id), "--hard",
    )

    wait_for(
        "pm board visible",
        lambda: _assert_board_get(board_id),
    )

    # 3. Columns. Stable IDs so tests can reference them by name.
    column_specs = [
        ("status", "status", "Status"),
        ("person", "people", "Owner"),
        ("date", "date", "Due Date"),
        ("timeline", "timeline", "Timeline"),
        ("numbers", "numbers", "Story Points"),
        ("text", "text", "Owner Email"),
        ("long_text", "long_text", "Description"),
        ("doc", "doc", "Spec Doc"),
    ]
    column_ids: dict[str, str] = {}
    for logical, col_type, title in column_specs:
        col_id = f"e2e_{logical}"
        result = invoke_json(
            [
                "column", "create",
                "--board", str(board_id),
                "--title", title,
                "--type", col_type,
                "--id", col_id,
            ]
        )
        column_ids[logical] = result["id"]

    # 4. Groups
    group_specs = [
        ("backlog", "Backlog"),
        ("in_progress", "In Progress"),
        ("done", "Done"),
    ]
    group_ids: dict[str, str] = {}
    for logical, title in group_specs:
        result = invoke_json(
            [
                "group", "create",
                "--board", str(board_id),
                "--name", title,
            ]
        )
        group_ids[logical] = result["id"]

    # 5. Items — 5 distributed across the 3 groups with column values.
    item_specs = [
        ("Design login flow", "backlog", "5", "design@e2e.test", "Initial spec for login + 2FA."),
        ("Refactor auth middleware", "backlog", "8", "auth@e2e.test", "Strip session token storage."),
        ("Implement OAuth callback", "in_progress", "3", "oauth@e2e.test", "Wire callback endpoint."),
        ("QA login regression", "in_progress", "2", "qa@e2e.test", "Cover edge cases."),
        ("Ship v2 launch", "done", "13", "pm@e2e.test", "All gates closed; ramp 100%."),
    ]
    item_ids: list[int] = []
    item_names: list[str] = []
    for name, group_logical, points, email, description in item_specs:
        result = invoke_json(
            [
                "item", "create",
                "--board", str(board_id),
                "--group", group_ids[group_logical],
                "--name", name,
                "--column", f"{column_ids['numbers']}={points}",
                "--column", f"{column_ids['text']}={email}",
                "--column", f"{column_ids['long_text']}={description}",
            ]
        )
        item_id = int(result["id"])
        item_ids.append(item_id)
        item_names.append(name)
        # No per-item cleanup — folder/board cascade handles it.

    # Sanity probe: all items visible.
    wait_for(
        "pm board items visible",
        lambda: _assert_items_present(board_id, item_ids),
    )

    return PmBoard(
        workspace_id=workspace_id,
        folder_id=folder_id,
        board_id=board_id,
        column_ids=column_ids,
        group_ids=group_ids,
        item_ids=item_ids,
        item_names=item_names,
    )


# ---------------------------------------------------------------------------
# Internal probes used during session-fixture setup
# ---------------------------------------------------------------------------


def _assert_board_get(board_id: int) -> None:
    result = invoke(["board", "get", "--id", str(board_id)], expect_exit=None)
    assert result.exit_code == 0, f"board {board_id} not yet visible"


def _assert_items_present(board_id: int, item_ids: list[int]) -> None:
    listing = invoke_json(["item", "list", "--board", str(board_id)])
    seen = {int(item["id"]) for item in listing}
    missing = [iid for iid in item_ids if iid not in seen]
    assert not missing, f"items not yet visible on board {board_id}: {missing}"
