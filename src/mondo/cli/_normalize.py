"""Rename entity-prefixed keys to their shared-shape counterparts so
`board list` and `doc list` emit drop-in comparable core fields.

Monday's `Board` uses `board_kind` / `board_folder_id`; `Doc` uses
`doc_kind` / `doc_folder_id`. Both become `kind` / `folder_id` at the
cache/CLI boundary.
"""

from __future__ import annotations

from typing import Any


def _normalize_entry(entry: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    """Return a copy of `entry` with `<prefix>_kind` → `kind` and
    `<prefix>_folder_id` → `folder_id`."""
    out = dict(entry)
    if f"{prefix}_kind" in out:
        out["kind"] = out.pop(f"{prefix}_kind")
    if f"{prefix}_folder_id" in out:
        out["folder_id"] = out.pop(f"{prefix}_folder_id")
    return out


def normalize_board_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return _normalize_entry(entry, prefix="board")


def normalize_doc_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return _normalize_entry(entry, prefix="doc")


def normalize_folder_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested `workspace` and `parent` dicts into scalar keys.

    Input shape (from GraphQL):
        workspace: {id, name} | None
        parent:    {id, name} | None

    Output shape:
        workspace_id, workspace_name, parent_id, parent_name
    """
    workspace = entry.get("workspace") or {}
    parent = entry.get("parent") or {}
    return {
        "id": entry.get("id"),
        "name": entry.get("name"),
        "color": entry.get("color"),
        "workspace_id": workspace.get("id"),
        "workspace_name": workspace.get("name"),
        "parent_id": parent.get("id"),
        "parent_name": parent.get("name"),
        "created_at": entry.get("created_at"),
        "owner_id": entry.get("owner_id"),
    }
