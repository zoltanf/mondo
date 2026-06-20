"""Live integration tests for subitem create/list/get/columns/move/delete.

Each test owns its own parent item on the session PM board and cleans it
up — never touches the original 5 fixture items.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from ._helpers import (
    CleanupPlan,
    invoke_json,
    wait_for,
)
from .conftest import PmBoard


def _scratch_parent(pm: PmBoard, cleanup_plan: CleanupPlan, suffix: str) -> int:
    item = invoke_json(
        [
            "item",
            "create",
            "--board",
            str(pm.board_id),
            "--group",
            pm.group_ids["backlog"],
            "--name",
            f"E2E Subitem Parent {suffix}",
        ]
    )
    item_id = int(item["id"])
    cleanup_plan.add(
        f"subitem parent {item_id}",
        "item",
        "delete",
        "--id",
        str(item_id),
        "--hard",
    )
    return item_id


@pytest.mark.integration
def test_live_subitem_create_and_list(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    """Create 3 subitems on a fresh parent; assert they list back."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    parent_id = _scratch_parent(pm, cleanup_plan, suffix)

    created_ids: list[int] = []
    for i in range(3):
        sub = invoke_json(
            [
                "subitem",
                "create",
                "--parent",
                str(parent_id),
                "--name",
                f"E2E Sub {suffix} #{i}",
            ]
        )
        sub_id = int(sub["id"])
        created_ids.append(sub_id)
        cleanup_plan.add(
            f"subitem {sub_id}",
            "subitem",
            "delete",
            "--id",
            str(sub_id),
            "--hard",
        )

    def _all_visible() -> list[dict[str, Any]]:
        listing = invoke_json(["subitem", "list", "--parent", str(parent_id)])
        seen = {int(s["id"]) for s in listing}
        missing = [sid for sid in created_ids if sid not in seen]
        assert not missing, f"subitems missing from listing: {missing}"
        return listing

    wait_for("3 subitems visible", _all_visible)


@pytest.mark.integration
def test_live_subitem_set_and_get_column_value(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """Set a text column on a subitem; round-trip via `subitem get`."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    parent_id = _scratch_parent(pm, cleanup_plan, suffix)

    sub = invoke_json(
        [
            "subitem",
            "create",
            "--parent",
            str(parent_id),
            "--name",
            f"E2E Sub Col {suffix}",
        ]
    )
    sub_id = int(sub["id"])
    cleanup_plan.add(
        f"sub col {sub_id}",
        "subitem",
        "delete",
        "--id",
        str(sub_id),
        "--hard",
    )

    # Subitems live on a separate auto-generated board with its own column ids.
    # Find a text column on that board.
    sub_listing = wait_for(
        "subitem listed",
        lambda: invoke_json(["subitem", "list", "--parent", str(parent_id)]),
    )
    sub_board_id = None
    for s in sub_listing:
        if int(s["id"]) == sub_id:
            sub_board_id = (s.get("board") or {}).get("id")
            break
    assert sub_board_id, "could not resolve subitems board id"

    sub_columns = invoke_json(["column", "list", "--board", str(sub_board_id)])
    text_col = next((c for c in sub_columns if c.get("type") == "text"), None)
    if text_col is None:
        # Subitems boards by default only have a name column; create a text
        # column so we have somewhere to write.
        created = invoke_json(
            [
                "column",
                "create",
                "--board",
                str(sub_board_id),
                "--title",
                "E2E Sub Text",
                "--type",
                "text",
                "--id",
                "e2e_sub_text",
            ]
        )
        text_col_id = created["id"]
    else:
        text_col_id = text_col["id"]

    text_value = f"e2e text {suffix}"
    invoke_json(
        [
            "column",
            "set",
            "--item",
            str(sub_id),
            "--column",
            text_col_id,
            "--value",
            text_value,
        ]
    )

    def _value_landed() -> None:
        got = invoke_json(["subitem", "get", "--id", str(sub_id)])
        values = {v["id"]: v.get("text", "") for v in got.get("column_values") or []}
        assert values.get(text_col_id) == text_value, f"text col={values.get(text_col_id)!r}"

    wait_for("subitem text column landed", _value_landed)


@pytest.mark.integration
def test_live_subitem_create_with_tags_codec_resolves_names(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """`subitem create --subitems-board --column <tags>=name` resolves the tag
    name to an id via create_or_get_tag, matching `item create`.

    Regression for the subitem path that previously skipped tag resolution:
    a bare name hit the tags codec and exited 5. The successful create alone
    proves the fix (the old path would have errored); the round-trip confirms
    the resolved tag actually landed on the subitem.
    """
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    parent_id = _scratch_parent(pm, cleanup_plan, suffix)

    # Materialize the subitems board via a throwaway name-only subitem.
    seed = invoke_json(
        ["subitem", "create", "--parent", str(parent_id), "--name", f"E2E Seed {suffix}"]
    )
    seed_id = int(seed["id"])
    cleanup_plan.add(f"subitem seed {seed_id}", "subitem", "delete", "--id", str(seed_id), "--hard")

    sub_listing = wait_for(
        "seed subitem listed",
        lambda: invoke_json(["subitem", "list", "--parent", str(parent_id)]),
    )
    sub_board_id = None
    for s in sub_listing:
        if int(s["id"]) == seed_id:
            sub_board_id = (s.get("board") or {}).get("id")
            break
    assert sub_board_id, "could not resolve subitems board id"

    # Ensure a tags column exists on the subitems board (default boards have none).
    sub_columns = invoke_json(["column", "list", "--board", str(sub_board_id)])
    tags_col = next((c for c in sub_columns if c.get("type") == "tags"), None)
    if tags_col is None:
        created = invoke_json(
            [
                "column",
                "create",
                "--board",
                str(sub_board_id),
                "--title",
                "E2E Sub Tags",
                "--type",
                "tags",
                "--id",
                "e2e_sub_tags",
            ]
        )
        tags_col_id = created["id"]
    else:
        tags_col_id = tags_col["id"]

    # The actual fix under test: a bare tag NAME on subitem create.
    tag_name = f"E2ETag{suffix}"
    sub = invoke_json(
        [
            "subitem",
            "create",
            "--parent",
            str(parent_id),
            "--name",
            f"E2E Sub Tags {suffix}",
            "--subitems-board",
            str(sub_board_id),
            "--column",
            f"{tags_col_id}={tag_name}",
        ]
    )
    sub_id = int(sub["id"])
    cleanup_plan.add(f"subitem tags {sub_id}", "subitem", "delete", "--id", str(sub_id), "--hard")

    def _tag_landed() -> None:
        got = invoke_json(["subitem", "get", "--id", str(sub_id)])
        cv = {v["id"]: v for v in got.get("column_values") or []}
        col = cv.get(tags_col_id)
        assert col is not None, f"tags column {tags_col_id} missing: {list(cv)}"
        text = col.get("text") or ""
        ids: list[int] = []
        raw_value = col.get("value")
        if raw_value:
            try:
                ids = (json.loads(raw_value) or {}).get("tag_ids") or []
            except json.JSONDecodeError, TypeError:
                ids = []
        assert tag_name in text or ids, f"tag not resolved: text={text!r} value={raw_value!r}"

    wait_for("subitem tag column landed", _tag_landed)


@pytest.mark.integration
def test_live_subitem_delete_hard(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    """`subitem delete --hard` removes the subitem from the parent's listing."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    parent_id = _scratch_parent(pm, cleanup_plan, suffix)

    sub = invoke_json(
        [
            "subitem",
            "create",
            "--parent",
            str(parent_id),
            "--name",
            f"E2E Sub Delete {suffix}",
        ]
    )
    sub_id = int(sub["id"])

    def _present() -> None:
        listing = invoke_json(["subitem", "list", "--parent", str(parent_id)])
        ids = {int(s["id"]) for s in listing}
        assert sub_id in ids, f"subitem {sub_id} not yet visible"

    wait_for("subitem present before delete", _present)

    # Delete explicitly; no cleanup_plan entry needed for the subitem itself
    # (the parent item cleanup cascades, but we're testing delete works).
    invoke_json(["subitem", "delete", "--id", str(sub_id), "--hard"])

    def _gone() -> None:
        listing = invoke_json(["subitem", "list", "--parent", str(parent_id)])
        ids = {int(s["id"]) for s in listing}
        assert sub_id not in ids, f"subitem {sub_id} still in listing after hard-delete"

    wait_for("subitem gone after delete", _gone)


def _make_subitem(parent_id: int, cleanup_plan: CleanupPlan, name: str) -> int:
    sub = invoke_json(["subitem", "create", "--parent", str(parent_id), "--name", name])
    sub_id = int(sub["id"])
    cleanup_plan.add(f"subitem {sub_id}", "subitem", "delete", "--id", str(sub_id), "--hard")
    return sub_id


def _subitems_board_id(parent_id: int) -> int:
    listing = wait_for(
        "subitems listed",
        lambda: invoke_json(["subitem", "list", "--parent", str(parent_id)]),
    )
    board_id = (listing[0].get("board") or {}).get("id")
    assert board_id, f"could not resolve subitems board id: {listing}"
    return int(board_id)


@pytest.mark.integration
def test_live_subitem_rename(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    parent_id = _scratch_parent(pm, cleanup_plan, suffix)
    sub_id = _make_subitem(parent_id, cleanup_plan, f"E2E Sub Rename {suffix}")
    sub_board_id = _subitems_board_id(parent_id)

    new_name = f"E2E Sub Renamed {suffix}"
    invoke_json(
        ["subitem", "rename", "--id", str(sub_id), "--board", str(sub_board_id), "--name", new_name]
    )

    def _renamed() -> None:
        got = invoke_json(["subitem", "get", "--id", str(sub_id)])
        assert got["name"] == new_name, f"name={got['name']!r}"

    wait_for("subitem renamed", _renamed)


@pytest.mark.integration
def test_live_subitem_archive(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    parent_id = _scratch_parent(pm, cleanup_plan, suffix)
    sub_id = _make_subitem(parent_id, cleanup_plan, f"E2E Sub Archive {suffix}")

    invoke_json(["subitem", "archive", "--id", str(sub_id)])

    def _gone() -> None:
        ids = {int(s["id"]) for s in invoke_json(["subitem", "list", "--parent", str(parent_id)])}
        assert sub_id not in ids, f"subitem {sub_id} still active after archive"

    wait_for("subitem archived", _gone)


@pytest.mark.integration
def test_live_subitem_move_dry_run(pm_board_session: PmBoard, cleanup_plan: CleanupPlan) -> None:
    """`subitem move` dispatches `move_item_to_group`.

    A real move can't be exercised on this account: every subitem lives in
    the subitems board's single `topics` group, and monday refuses to create
    a second group there (`GroupActionOnSubitemBoardException`). So there is
    no distinct target group to move into — the command path is verified via
    --dry-run instead, against a real subitem id.
    """
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    parent_id = _scratch_parent(pm, cleanup_plan, suffix)
    sub_id = _make_subitem(parent_id, cleanup_plan, f"E2E Sub Move {suffix}")

    out = invoke_json(["--dry-run", "subitem", "move", "--id", str(sub_id), "--group", "topics"])
    assert "move_item_to_group" in out["query"], out["query"]
    assert out["variables"]["id"] == sub_id and out["variables"]["group"] == "topics"
