"""Rename entity-prefixed keys to their shared-shape counterparts so
`board list` and `doc list` emit drop-in comparable core fields.

Monday's `Board` uses `board_kind` / `board_folder_id`; `Doc` uses
`doc_kind` / `doc_folder_id`. Both become `kind` / `folder_id` at the
cache/CLI boundary.
"""

from __future__ import annotations

from typing import Any


def _rename_key(entry: dict[str, Any], *, old: str, new: str) -> dict[str, Any]:
    """Rename a key while preserving insertion order."""
    if old not in entry:
        return dict(entry)
    out: dict[str, Any] = {}
    for key, value in entry.items():
        out[new if key == old else key] = value
    return out


def _ensure_workspace_pair_order(entry: dict[str, Any]) -> dict[str, Any]:
    """When both fields exist, keep `workspace_name` immediately after `workspace_id`."""
    if "workspace_id" not in entry or "workspace_name" not in entry:
        return dict(entry)
    out: dict[str, Any] = {}
    ws_name = entry.get("workspace_name")
    for key, value in entry.items():
        if key == "workspace_name":
            continue
        out[key] = value
        if key == "workspace_id":
            out["workspace_name"] = ws_name
    return out


def _move_timestamps_to_tail(entry: dict[str, Any]) -> dict[str, Any]:
    """Move created/updated timestamps to the end when present."""
    out = dict(entry)
    for key in ("created_at", "updated_at"):
        if key in out:
            value = out.pop(key)
            out[key] = value
    return out


def _normalize_entry(entry: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    """Return a copy of `entry` with `<prefix>_kind` → `kind` and
    `<prefix>_folder_id` → `folder_id`."""
    out = dict(entry)
    out = _rename_key(out, old=f"{prefix}_kind", new="kind")
    out = _rename_key(out, old=f"{prefix}_folder_id", new="folder_id")
    out = _ensure_workspace_pair_order(out)
    out = _move_timestamps_to_tail(out)
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
    out = {
        "id": entry.get("id"),
        "name": entry.get("name"),
        "color": entry.get("color"),
        "workspace_id": workspace.get("id"),
        "workspace_name": workspace.get("name"),
        "parent_id": parent.get("id"),
        "parent_name": parent.get("name"),
        "owner_id": entry.get("owner_id"),
        "created_at": entry.get("created_at"),
    }
    return _move_timestamps_to_tail(out)
