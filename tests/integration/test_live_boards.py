"""Live integration tests for `mondo board duplicate` (3 variants) and `mondo board move`."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from ._helpers import (
    CleanupPlan,
    invoke,
    invoke_json,
    wait_for,
)
from .conftest import PmBoard


def _wait_for_board_get(board_id: int) -> dict[str, Any]:
    return wait_for(
        f"board {board_id} visible",
        lambda: invoke_json(["board", "get", "--id", str(board_id)]),
    )


def _board_id_from_duplicate(payload: dict[str, Any]) -> int:
    """Pluck the new board's id out of `mondo board duplicate`'s response.

    The CLI emits the raw `duplicate_board` payload: `{board: {id, ...}, ...}`.
    """
    board = payload.get("board")
    if isinstance(board, dict) and board.get("id") is not None:
        return int(board["id"])
    if "id" in payload:
        return int(payload["id"])
    raise AssertionError(f"no board id in duplicate payload: {payload}")


@pytest.mark.integration
def test_live_board_duplicate_with_structure_only(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """duplicate_board_with_structure copies columns + groups but not items."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]

    duplicated = invoke_json(
        [
            "board", "duplicate", str(pm.board_id),
            "--type", "duplicate_board_with_structure",
            "--name", f"E2E Dup Structure {suffix}",
            "--workspace", str(pm.workspace_id),
            "--folder", str(pm.folder_id),
        ]
    )
    new_board_id = _board_id_from_duplicate(duplicated)
    cleanup_plan.add(
        f"dup-structure {new_board_id}",
        "board", "delete", "--id", str(new_board_id), "--hard",
    )

    _wait_for_board_get(new_board_id)

    # Source columns + groups all copied.
    src_columns = invoke_json(["column", "list", "--board", str(pm.board_id)])
    new_columns = invoke_json(["column", "list", "--board", str(new_board_id)])
    src_titles = sorted(c["title"] for c in src_columns)
    new_titles = sorted(c["title"] for c in new_columns)
    assert src_titles == new_titles, f"column titles mismatch: src={src_titles}, new={new_titles}"

    src_groups = invoke_json(["group", "list", "--board", str(pm.board_id)])
    new_groups = invoke_json(["group", "list", "--board", str(new_board_id)])
    src_g_titles = sorted(g["title"] for g in src_groups)
    new_g_titles = sorted(g["title"] for g in new_groups)
    assert src_g_titles == new_g_titles, f"group titles mismatch: src={src_g_titles}, new={new_g_titles}"

    # Zero items.
    new_items = invoke_json(["item", "list", "--board", str(new_board_id)])
    assert len(new_items) == 0, f"structure-only dup carried items: {new_items}"


@pytest.mark.integration
def test_live_board_duplicate_with_pulses(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """duplicate_board_with_pulses copies items but no updates."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]

    duplicated = invoke_json(
        [
            "board", "duplicate", str(pm.board_id),
            "--type", "duplicate_board_with_pulses",
            "--name", f"E2E Dup Pulses {suffix}",
            "--workspace", str(pm.workspace_id),
            "--folder", str(pm.folder_id),
            "--wait",
        ]
    )
    new_board_id = _board_id_from_duplicate(duplicated)
    cleanup_plan.add(
        f"dup-pulses {new_board_id}",
        "board", "delete", "--id", str(new_board_id), "--hard",
    )

    def _items_landed() -> list[dict[str, Any]]:
        items = invoke_json(["item", "list", "--board", str(new_board_id)])
        assert len(items) >= len(pm.item_ids), f"only {len(items)} items landed"
        return items

    items = wait_for("duplicated items visible", _items_landed)
    copied_names = {i["name"] for i in items}
    for expected in pm.item_names:
        assert expected in copied_names, f"item {expected!r} not in duplicate"


@pytest.mark.integration
def test_live_board_duplicate_with_pulses_and_updates(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """duplicate_board_with_pulses_and_updates carries item updates over."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]

    # Create a scratch item on the session board so the update we post stays
    # confined to a row we own (and can clean up). Pure cleanup-of-the-update
    # is awkward through the API, so deleting the parent item handles it.
    scratch_name = f"E2E Dup Update Source {suffix}"
    scratch = invoke_json(
        [
            "item", "create",
            "--board", str(pm.board_id),
            "--group", pm.group_ids["backlog"],
            "--name", scratch_name,
        ]
    )
    scratch_id = int(scratch["id"])
    cleanup_plan.add(
        f"scratch item {scratch_id}",
        "item", "delete", "--id", str(scratch_id), "--hard",
    )

    update_body = f"E2E duplicated update marker {suffix}"
    invoke_json(
        [
            "update", "create",
            "--item", str(scratch_id),
            "--body", update_body,
        ]
    )

    duplicated = invoke_json(
        [
            "board", "duplicate", str(pm.board_id),
            "--type", "duplicate_board_with_pulses_and_updates",
            "--name", f"E2E Dup Full {suffix}",
            "--workspace", str(pm.workspace_id),
            "--folder", str(pm.folder_id),
            "--wait",
        ]
    )
    new_board_id = _board_id_from_duplicate(duplicated)
    cleanup_plan.add(
        f"dup-full {new_board_id}",
        "board", "delete", "--id", str(new_board_id), "--hard",
    )

    def _scratch_clone_visible() -> int:
        items = invoke_json(["item", "list", "--board", str(new_board_id)])
        match = next((i for i in items if i["name"] == scratch_name), None)
        assert match is not None, f"scratch item not in duplicate: {[i['name'] for i in items]}"
        return int(match["id"])

    cloned_item_id = wait_for("scratch clone visible", _scratch_clone_visible)

    def _updates_landed() -> list[dict[str, Any]]:
        ups = invoke_json(["update", "list", "--item", str(cloned_item_id)])
        bodies = [
            (u.get("text_body") or "") + str(u.get("body") or "")
            for u in ups
        ]
        joined = "\n".join(bodies)
        assert update_body in joined, f"duplicate missing update body on cloned item: {joined[:300]}"
        return ups

    wait_for("duplicate carries updates", _updates_landed)


@pytest.mark.integration
def test_live_board_move_between_folders(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """Create folders A & B, create board in A, move it to B, verify hierarchy."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]

    folder_a = invoke_json(
        [
            "folder", "create",
            "--workspace", str(pm.workspace_id),
            "--name", f"E2E Move A {suffix}",
        ]
    )
    folder_a_id = int(folder_a["id"])
    cleanup_plan.add(
        f"folder A {folder_a_id}",
        "folder", "delete", "--id", str(folder_a_id), "--hard",
    )

    folder_b = invoke_json(
        [
            "folder", "create",
            "--workspace", str(pm.workspace_id),
            "--name", f"E2E Move B {suffix}",
        ]
    )
    folder_b_id = int(folder_b["id"])
    cleanup_plan.add(
        f"folder B {folder_b_id}",
        "folder", "delete", "--id", str(folder_b_id), "--hard",
    )

    board = invoke_json(
        [
            "board", "create",
            "--workspace", str(pm.workspace_id),
            "--folder", str(folder_a_id),
            "--name", f"E2E Mover {suffix}",
            "--kind", "private",
            "--empty",
        ]
    )
    board_id = int(board["id"])
    cleanup_plan.add(
        f"mover board {board_id}",
        "board", "delete", "--id", str(board_id), "--hard",
    )

    def _board_in_folder(expected_folder_id: int) -> dict[str, Any]:
        b = invoke_json(["board", "get", "--id", str(board_id)])
        actual = int(b.get("folder_id") or 0)
        assert actual == expected_folder_id, f"board folder_id={actual}, want {expected_folder_id}"
        return b

    wait_for("board initially in A", lambda: _board_in_folder(folder_a_id))

    invoke_json(
        [
            "board", "move", str(board_id),
            "--folder", str(folder_b_id),
        ]
    )

    wait_for("board moved to B", lambda: _board_in_folder(folder_b_id))
