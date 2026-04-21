"""Rename entity-prefixed keys to their shared-shape counterparts so
`board list` and `doc list` emit drop-in comparable core fields.

Monday's `Board` uses `board_kind` / `board_folder_id`; `Doc` uses
`doc_kind` / `doc_folder_id`. Both become `kind` / `folder_id` at the
cache/CLI boundary.
"""

from __future__ import annotations

from typing import Any


def normalize_board_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `entry` with `board_kind` → `kind` and
    `board_folder_id` → `folder_id`."""
    out = dict(entry)
    if "board_kind" in out:
        out["kind"] = out.pop("board_kind")
    if "board_folder_id" in out:
        out["folder_id"] = out.pop("board_folder_id")
    return out


def normalize_doc_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `entry` with `doc_kind` → `kind` and
    `doc_folder_id` → `folder_id`."""
    out = dict(entry)
    if "doc_kind" in out:
        out["kind"] = out.pop("doc_kind")
    if "doc_folder_id" in out:
        out["folder_id"] = out.pop("doc_folder_id")
    return out
