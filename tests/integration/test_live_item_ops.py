"""Live integration tests for item lifecycle ops not covered elsewhere:
`item rename`, `item duplicate`, `item find`, `item move`,
`item move-to-board`, and `item archive`.

Every test builds its own scratch item(s) on the session PM board and
cleans up — the original 5 fixture items are never touched.
"""

from __future__ import annotations

import uuid

import pytest

from ._helpers import CleanupPlan, invoke_json, wait_for
from .conftest import PmBoard


def _scratch_item(pm: PmBoard, cleanup_plan: CleanupPlan, suffix: str, **columns: str) -> int:
    args = [
        "item",
        "create",
        "--board",
        str(pm.board_id),
        "--group",
        pm.group_ids["backlog"],
        "--name",
        f"E2E Item Op {suffix}",
    ]
    for col_id, value in columns.items():
        args += ["--column", f"{col_id}={value}"]
    item = invoke_json(args)
    item_id = int(item["id"])
    cleanup_plan.add(f"item {item_id}", "item", "delete", "--id", str(item_id), "--hard")
    return item_id


@pytest.mark.integration
def test_live_item_rename(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    item_id = _scratch_item(pm, cleanup_plan, suffix)

    new_name = f"E2E Renamed {suffix}"
    invoke_json(
        ["item", "rename", "--id", str(item_id), "--board", str(pm.board_id), "--name", new_name]
    )

    def _renamed() -> None:
        got = invoke_json(["item", "get", "--id", str(item_id)])
        assert got["name"] == new_name, f"name={got['name']!r}"

    wait_for("item renamed", _renamed)


@pytest.mark.integration
def test_live_item_duplicate(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    item_id = _scratch_item(pm, cleanup_plan, suffix)

    dup = invoke_json(["item", "duplicate", str(item_id), "--board", str(pm.board_id)])
    dup_id = int(dup["id"])
    cleanup_plan.add(f"item dup {dup_id}", "item", "delete", "--id", str(dup_id), "--hard")
    assert dup_id != item_id

    def _dup_visible() -> None:
        got = invoke_json(["item", "get", "--id", str(dup_id)])
        assert int(got["id"]) == dup_id

    wait_for("duplicate visible", _dup_visible)


@pytest.mark.integration
def test_live_item_find_by_column_value(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """`item find --column <text> --value <unique>` returns the matching item."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    unique = f"find-{suffix}@e2e.test"
    item_id = _scratch_item(pm, cleanup_plan, suffix, **{pm.column_ids["text"]: unique})

    def _found() -> None:
        found = invoke_json(
            [
                "item",
                "find",
                "--board",
                str(pm.board_id),
                "--column",
                pm.column_ids["text"],
                "--value",
                unique,
            ]
        )
        ids = {int(i["id"]) for i in found}
        assert item_id in ids, f"item {item_id} not found via text filter: {ids}"

    wait_for("item find matched", _found)


@pytest.mark.integration
def test_live_item_move_between_groups(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    item_id = _scratch_item(pm, cleanup_plan, suffix)

    invoke_json(["item", "move", "--id", str(item_id), "--group", pm.group_ids["done"]])

    def _moved() -> None:
        got = invoke_json(["item", "get", "--id", str(item_id)])
        assert (got.get("group") or {}).get("id") == pm.group_ids["done"], got.get("group")

    wait_for("item moved group", _moved)


@pytest.mark.integration
def test_live_item_archive(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    """Archived items drop out of the default (active) item listing."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    item_id = _scratch_item(pm, cleanup_plan, suffix)

    def _present() -> None:
        ids = {int(i["id"]) for i in invoke_json(["item", "list", "--board", str(pm.board_id)])}
        assert item_id in ids

    wait_for("item present before archive", _present)

    invoke_json(["item", "archive", "--id", str(item_id)])

    def _gone() -> None:
        ids = {int(i["id"]) for i in invoke_json(["item", "list", "--board", str(pm.board_id)])}
        assert item_id not in ids, f"item {item_id} still active after archive"

    wait_for("item gone after archive", _gone)


@pytest.mark.integration
def test_live_item_move_to_board(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    """Move an item onto a schema-identical destination board (a structure-only
    duplicate), so no `--column-mapping` is required."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]

    dest = invoke_json(
        [
            "board",
            "duplicate",
            str(pm.board_id),
            "--type",
            "duplicate_board_with_structure",
            "--name",
            f"E2E Move Dest {suffix}",
            "--workspace",
            str(pm.workspace_id),
            "--folder",
            str(pm.folder_id),
        ]
    )
    dest_board_id = int((dest.get("board") or dest)["id"])
    cleanup_plan.add(
        f"move dest board {dest_board_id}", "board", "delete", "--id", str(dest_board_id), "--hard"
    )

    dest_group_id = wait_for(
        "dest board groups",
        lambda: invoke_json(["group", "list", "--board", str(dest_board_id)]),
    )[0]["id"]

    item_id = _scratch_item(pm, cleanup_plan, suffix)
    invoke_json(
        [
            "item",
            "move-to-board",
            "--id",
            str(item_id),
            "--to-board",
            str(dest_board_id),
            "--to-group",
            dest_group_id,
        ]
    )

    def _on_dest() -> None:
        ids = {int(i["id"]) for i in invoke_json(["item", "list", "--board", str(dest_board_id)])}
        assert item_id in ids, f"item {item_id} not on destination board: {ids}"

    wait_for("item moved to board", _on_dest)
