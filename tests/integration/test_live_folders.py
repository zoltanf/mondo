"""Live integration tests for folder tree, create+nest, position, delete-archives-board."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from ._helpers import (
    CleanupPlan,
    invoke,
    invoke_json,
    wait_for,
)


def _list_folders_in_workspace(workspace_id: int) -> list[dict[str, Any]]:
    return invoke_json(
        ["folder", "list", "--workspace", str(workspace_id), "--no-cache"]
    )


@pytest.mark.integration
def test_live_folder_tree_renders_hierarchy(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    """`mondo folder tree` returns the new subtree with correct nesting."""
    suffix = uuid.uuid4().hex[:8]

    root = invoke_json(
        [
            "folder", "create",
            "--workspace", str(live_workspace_id),
            "--name", f"E2E Tree Root {suffix}",
        ]
    )
    root_id = int(root["id"])
    cleanup_plan.add(
        f"tree root {root_id}",
        "folder", "delete", "--id", str(root_id), "--hard",
    )

    alpha = invoke_json(
        [
            "folder", "create",
            "--workspace", str(live_workspace_id),
            "--parent", str(root_id),
            "--name", f"E2E Tree Alpha {suffix}",
        ]
    )
    alpha_id = int(alpha["id"])
    cleanup_plan.add(
        f"tree alpha {alpha_id}",
        "folder", "delete", "--id", str(alpha_id), "--hard",
    )

    beta = invoke_json(
        [
            "folder", "create",
            "--workspace", str(live_workspace_id),
            "--parent", str(root_id),
            "--name", f"E2E Tree Beta {suffix}",
        ]
    )
    beta_id = int(beta["id"])
    cleanup_plan.add(
        f"tree beta {beta_id}",
        "folder", "delete", "--id", str(beta_id), "--hard",
    )

    grandchild = invoke_json(
        [
            "folder", "create",
            "--workspace", str(live_workspace_id),
            "--parent", str(alpha_id),
            "--name", f"E2E Tree Alpha.1 {suffix}",
        ]
    )
    grandchild_id = int(grandchild["id"])
    cleanup_plan.add(
        f"tree alpha.1 {grandchild_id}",
        "folder", "delete", "--id", str(grandchild_id), "--hard",
    )

    def _tree_has_subtree() -> dict[str, Any]:
        # `folder tree` nests via sub_folders rather than parent_id. Build a
        # child -> parent map by walking sub_folders. Then assert the four
        # new folders show up with the expected relationships.
        result = invoke(
            ["folder", "tree", "--workspace", str(live_workspace_id), "--no-cache"],
            expect_exit=0,
        )
        tree = json.loads(result.stdout)
        child_to_parent: dict[int, int | None] = {}

        def walk(node: dict[str, Any], parent: int | None) -> None:
            fid_raw = node.get("id")
            if fid_raw is not None:
                child_to_parent[int(fid_raw)] = parent
                next_parent = int(fid_raw)
            else:
                next_parent = parent
            for child in node.get("sub_folders") or node.get("folders") or []:
                walk(child, next_parent)

        if isinstance(tree, list):
            for ws in tree:
                if isinstance(ws, dict):
                    for f in ws.get("folders") or []:
                        walk(f, None)
        elif isinstance(tree, dict):
            for f in tree.get("folders") or []:
                walk(f, None)

        for fid in (root_id, alpha_id, beta_id, grandchild_id):
            assert fid in child_to_parent, f"folder {fid} missing from tree"

        assert child_to_parent[alpha_id] == root_id, f"alpha parent={child_to_parent[alpha_id]}"
        assert child_to_parent[beta_id] == root_id, f"beta parent={child_to_parent[beta_id]}"
        assert child_to_parent[grandchild_id] == alpha_id, (
            f"alpha.1 parent={child_to_parent[grandchild_id]}"
        )
        return tree

    wait_for("folder subtree visible", _tree_has_subtree)


@pytest.mark.integration
def test_live_folder_create_with_parent_link(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    """`folder create --parent` actually nests; `folder get` shows the link."""
    suffix = uuid.uuid4().hex[:8]

    parent = invoke_json(
        [
            "folder", "create",
            "--workspace", str(live_workspace_id),
            "--name", f"E2E Parent {suffix}",
        ]
    )
    parent_id = int(parent["id"])
    cleanup_plan.add(
        f"parent {parent_id}",
        "folder", "delete", "--id", str(parent_id), "--hard",
    )

    child = invoke_json(
        [
            "folder", "create",
            "--workspace", str(live_workspace_id),
            "--parent", str(parent_id),
            "--name", f"E2E Child {suffix}",
        ]
    )
    child_id = int(child["id"])
    cleanup_plan.add(
        f"child {child_id}",
        "folder", "delete", "--id", str(child_id), "--hard",
    )

    def _child_links_to_parent() -> dict[str, Any]:
        got = invoke_json(["folder", "get", "--id", str(child_id)])
        raw = got.get("parent_id") or got.get("parent")
        if isinstance(raw, dict):
            raw = raw.get("id")
        actual = int(raw) if raw not in (None, "", 0, "0") else None
        assert actual == parent_id, f"child parent_id={actual}, want {parent_id}"
        return got

    wait_for("child links to parent", _child_links_to_parent)


@pytest.mark.integration
def test_live_folder_update_name_changes_listing(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    """`folder update --name` is reflected in subsequent `folder get` and listing."""
    suffix = uuid.uuid4().hex[:8]
    original_name = f"E2E Rename Before {suffix}"
    updated_name = f"E2E Rename After {suffix}"

    folder = invoke_json(
        [
            "folder", "create",
            "--workspace", str(live_workspace_id),
            "--name", original_name,
        ]
    )
    folder_id = int(folder["id"])
    cleanup_plan.add(
        f"renamed folder {folder_id}",
        "folder", "delete", "--id", str(folder_id), "--hard",
    )

    invoke_json(
        [
            "folder", "update", str(folder_id),
            "--name", updated_name,
        ]
    )

    def _rename_visible() -> None:
        got = invoke_json(["folder", "get", "--id", str(folder_id)])
        assert got.get("name") == updated_name, f"folder name={got.get('name')!r}"
        listing = _list_folders_in_workspace(live_workspace_id)
        names = {f.get("name") for f in listing}
        assert updated_name in names, f"updated name not in listing"
        assert original_name not in names, f"old name still in listing"

    wait_for("rename visible", _rename_visible)


@pytest.mark.integration
def test_live_folder_delete_archives_contained_board(
    live_workspace_id: int, cleanup_plan: CleanupPlan
) -> None:
    """Deleting a folder archives the boards inside it (per CLI help text)."""
    suffix = uuid.uuid4().hex[:8]

    folder = invoke_json(
        [
            "folder", "create",
            "--workspace", str(live_workspace_id),
            "--name", f"E2E Archive Folder {suffix}",
        ]
    )
    folder_id = int(folder["id"])
    # No cleanup_plan entry: the test deletes the folder explicitly. If the
    # test crashes before that, the folder will linger — acceptable since this
    # is the only test that performs an explicit folder delete (cleanup_plan
    # would otherwise fail on the already-deleted folder).

    board = invoke_json(
        [
            "board", "create",
            "--workspace", str(live_workspace_id),
            "--folder", str(folder_id),
            "--name", f"E2E Archive Board {suffix}",
            "--kind", "private",
            "--empty",
        ]
    )
    board_id = int(board["id"])
    cleanup_plan.add(
        f"archive board {board_id}",
        "board", "delete", "--id", str(board_id), "--hard",
    )

    def _board_visible_active() -> dict[str, Any]:
        return invoke_json(["board", "get", "--id", str(board_id)])

    wait_for("board active before folder delete", _board_visible_active)

    # Delete the folder explicitly (cleanup_plan still cleans up if this fails).
    invoke_json(
        [
            "folder", "delete", str(folder_id), "--hard",
        ]
    )

    def _board_archived_or_deleted() -> dict[str, Any]:
        # `board get` returns exit-6 "not found" once the board leaves active
        # state. Confirm it shows up in a non-active listing — the API help
        # says folder delete archives contained boards, but in practice the
        # state may be "archived" or "deleted" depending on workspace policy.
        all_boards = invoke_json(
            [
                "board", "list",
                "--workspace", str(live_workspace_id),
                "--state", "all",
                "--no-cache",
            ]
        )
        match = next((b for b in all_boards if int(b.get("id", 0)) == board_id), None)
        active = invoke_json(
            [
                "board", "list",
                "--workspace", str(live_workspace_id),
                "--state", "active",
                "--no-cache",
            ]
        )
        active_ids = {int(b.get("id", 0)) for b in active}
        assert board_id not in active_ids, (
            f"board {board_id} still in active listing after folder delete"
        )
        # If the all-listing also dropped it, that's a stronger signal than the
        # CLI help suggests but still satisfies "deleting a folder takes the
        # contained boards out of the active set". Either outcome is fine.
        if match is not None:
            assert match.get("state") in {"archived", "deleted"}, (
                f"board state={match.get('state')!r} (expected archived/deleted)"
            )
        return match or {"id": board_id, "state": "absent"}

    wait_for("board archived/deleted after folder delete", _board_archived_or_deleted)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flatten_tree(tree: Any) -> list[dict[str, Any]]:
    """Walk a folder tree and return every node as a flat list."""
    flat: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if isinstance(node, dict):
            if "id" in node and (node.get("name") or node.get("title")):
                flat.append(node)
            for key in ("children", "folders", "items"):
                if key in node:
                    visit(node[key])
            # Tree may be grouped by workspace; descend into nested values.
            for value in node.values():
                if isinstance(value, (dict, list)) and value not in (
                    node.get("children"), node.get("folders"), node.get("items"),
                ):
                    visit(value)

    visit(tree)
    return flat
