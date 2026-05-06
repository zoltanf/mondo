"""Shared column-value helpers used by `cli/column.py` and `cli/item.py`.

These two command modules used to redefine `_parse_settings` and
`_resolve_tag_names_to_ids` independently. Pulling them here gives a
single place to evolve column-codec preflight + tag resolution.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mondo.api.errors import MondoError
from mondo.api.queries import CREATE_OR_GET_TAG
from mondo.cli._exec import exec_or_exit

if TYPE_CHECKING:
    from mondo.api.client import MondayClient


def parse_settings(raw: str | None) -> dict[str, Any]:
    """Best-effort parse of a column's `settings_str`.

    monday returns settings as an opaque JSON string; non-object payloads
    or parse errors collapse to `{}` so callers can treat absence and
    malformed identically.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def resolve_tag_names_to_ids(
    client: MondayClient,
    board_id: int,
    raw: str,
    *,
    cache: dict[str, int] | None = None,
) -> str:
    """Resolve a comma-separated list of tag names *or* ids to a comma-id string.

    Pure-int components pass through unchanged so `TagsCodec.parse()` can
    consume the output directly. Non-int names are passed to
    `create_or_get_tag` to mint or fetch the id.

    `cache` (when provided) memoises name → id within one CLI invocation —
    a 50-row batch tagging the same `urgent` label won't issue 50 identical
    `create_or_get_tag` mutations.
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return ""
    resolved_ids: list[int] = []
    for part in parts:
        if part.isdigit() or (part.startswith("-") and part[1:].isdigit()):
            resolved_ids.append(int(part))
            continue
        if cache is not None and part in cache:
            resolved_ids.append(cache[part])
            continue
        data = exec_or_exit(client, CREATE_OR_GET_TAG, {"name": part, "board": board_id})
        tag = data.get("create_or_get_tag") or {}
        tag_id = tag.get("id")
        if tag_id is None:
            raise MondoError(f"create_or_get_tag returned no id for name {part!r}")
        tag_id_int = int(tag_id)
        if cache is not None:
            cache[part] = tag_id_int
        resolved_ids.append(tag_id_int)
    return ",".join(str(i) for i in resolved_ids)
