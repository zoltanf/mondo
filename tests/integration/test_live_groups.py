"""Live integration tests for the group ops with no other coverage:
`group archive`, `group duplicate`, `group reorder`.

Each test creates its own scratch group(s) on the session PM board and
cleans them up — the 3 fixture groups are never touched.
"""

from __future__ import annotations

import uuid

import pytest

from ._helpers import CleanupPlan, invoke_json, wait_for
from .conftest import PmBoard


def _scratch_group(pm: PmBoard, cleanup_plan: CleanupPlan, label: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    group = invoke_json(
        ["group", "create", "--board", str(pm.board_id), "--name", f"E2E {label} {suffix}"]
    )
    gid = group["id"]
    cleanup_plan.add(
        f"group {gid}", "group", "delete", "--board", str(pm.board_id), "--id", gid, "--hard"
    )
    return gid


def _group_ids(board_id: int) -> list[str]:
    return [g["id"] for g in invoke_json(["group", "list", "--board", str(board_id)])]


@pytest.mark.integration
def test_live_group_archive(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    pm = pm_board_session
    del cleanup_plan  # no per-group cleanup: monday forbids deleting an archived
    # group (exit 3), and the session board teardown cascades it away anyway.
    suffix = uuid.uuid4().hex[:8]
    group = invoke_json(
        ["group", "create", "--board", str(pm.board_id), "--name", f"E2E Archive {suffix}"]
    )
    gid = group["id"]

    invoke_json(["group", "archive", "--board", str(pm.board_id), "--id", gid])

    def _gone() -> None:
        assert gid not in _group_ids(pm.board_id), f"group {gid} still listed after archive"

    wait_for("group archived", _gone)


@pytest.mark.integration
def test_live_group_duplicate(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    pm = pm_board_session
    gid = _scratch_group(pm, cleanup_plan, "DupSrc")

    new_title = f"E2E Dup Copy {uuid.uuid4().hex[:6]}"
    dup = invoke_json(
        ["group", "duplicate", "--board", str(pm.board_id), "--id", gid, "--title", new_title]
    )
    # duplicate_group returns the new group under `group` (or at top level).
    new_gid = (dup.get("group") or dup)["id"]
    assert new_gid != gid
    cleanup_plan.add(
        f"dup group {new_gid}",
        "group",
        "delete",
        "--board",
        str(pm.board_id),
        "--id",
        new_gid,
        "--hard",
    )

    def _both_present() -> None:
        ids = _group_ids(pm.board_id)
        assert gid in ids and new_gid in ids, ids

    wait_for("duplicate group present", _both_present)


@pytest.mark.integration
def test_live_group_reorder(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    """Reorder one scratch group before another and assert the new order."""
    pm = pm_board_session
    first = _scratch_group(pm, cleanup_plan, "ReorderA")
    second = _scratch_group(pm, cleanup_plan, "ReorderB")

    invoke_json(
        ["group", "reorder", "--board", str(pm.board_id), "--id", second, "--before", first]
    )

    def _reordered() -> None:
        ids = _group_ids(pm.board_id)
        assert ids.index(second) < ids.index(first), f"order not applied: {ids}"

    wait_for("group reordered", _reordered)
