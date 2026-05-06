"""Live integration tests for `mondo update` create/reply/edit/pin/like/delete."""

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


def _scratch_item(pm: PmBoard, cleanup_plan: CleanupPlan, suffix: str) -> int:
    item = invoke_json(
        [
            "item", "create",
            "--board", str(pm.board_id),
            "--group", pm.group_ids["backlog"],
            "--name", f"E2E Update Item {suffix}",
        ]
    )
    item_id = int(item["id"])
    cleanup_plan.add(
        f"update item {item_id}",
        "item", "delete", "--id", str(item_id), "--hard",
    )
    return item_id


def _bodies_for_item(item_id: int) -> list[str]:
    """Flatten every update + nested reply body into a list of strings."""
    ups = invoke_json(["update", "list", "--item", str(item_id)])
    out: list[str] = []
    for u in ups:
        out.append((u.get("text_body") or "") + "\n" + (u.get("body") or ""))
        for reply in u.get("replies") or []:
            out.append((reply.get("text_body") or "") + "\n" + (reply.get("body") or ""))
    return out


@pytest.mark.integration
def test_live_update_create_reply_edit_delete(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """Post a top-level update, reply to it, edit the reply body, delete both."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    item_id = _scratch_item(pm, cleanup_plan, suffix)

    top_body = f"e2e top-level marker {suffix}"
    top = invoke_json(
        [
            "update", "create",
            "--item", str(item_id),
            "--body", top_body,
        ]
    )
    top_id = int(top["id"])

    reply_original = f"e2e reply original {suffix}"
    reply = invoke_json(
        [
            "update", "reply",
            "--parent", str(top_id),
            "--body", reply_original,
        ]
    )
    reply_id = int(reply["id"])

    def _both_visible() -> None:
        joined = "\n".join(_bodies_for_item(item_id))
        assert top_body in joined, f"top-level missing: {joined[:300]}"
        assert reply_original in joined, f"reply missing: {joined[:300]}"

    wait_for("both updates visible", _both_visible)

    # Edit the reply.
    reply_edited = f"e2e reply EDITED {suffix}"
    invoke_json(
        [
            "update", "edit", str(reply_id),
            "--body", reply_edited,
        ]
    )

    def _edit_landed() -> None:
        joined = "\n".join(_bodies_for_item(item_id))
        assert reply_edited in joined, f"edit not visible: {joined[:300]}"
        assert reply_original not in joined, f"old body still visible: {joined[:300]}"

    wait_for("edit landed", _edit_landed)

    # Delete both.
    invoke_json(["update", "delete", str(reply_id)])
    invoke_json(["update", "delete", str(top_id)])

    def _both_gone() -> None:
        joined = "\n".join(_bodies_for_item(item_id))
        assert top_body not in joined, f"top still present: {joined[:300]}"
        assert reply_edited not in joined, f"reply still present: {joined[:300]}"

    wait_for("both deleted", _both_gone)


@pytest.mark.integration
def test_live_update_pin_and_like_lifecycle(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """Post an update, pin and like it, then unpin and unlike before delete."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    item_id = _scratch_item(pm, cleanup_plan, suffix)

    body = f"e2e pin/like marker {suffix}"
    posted = invoke_json(
        [
            "update", "create",
            "--item", str(item_id),
            "--body", body,
        ]
    )
    update_id = int(posted["id"])

    invoke_json(["update", "pin", str(update_id)])
    invoke_json(["update", "like", str(update_id)])

    def _pinned_and_liked() -> None:
        ups = invoke_json(["update", "list", "--item", str(item_id)])
        match = next((u for u in ups if int(u.get("id", 0)) == update_id), None)
        assert match is not None, f"posted update {update_id} not visible"
        # The CLI's update list returns enriched fields; tolerate variations.
        likes = match.get("likes") or match.get("liked_by") or []
        assert likes, f"update has no likes recorded: {match}"

    wait_for("pinned + liked", _pinned_and_liked)

    invoke_json(["update", "unlike", str(update_id)])
    invoke_json(["update", "unpin", str(update_id)])
    invoke_json(["update", "delete", str(update_id)])
