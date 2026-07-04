"""Business logic for the `mondo board` command group.

Type-filter matching, payload decoding, and the live `items_count` helpers
extracted from :mod:`mondo.cli.board`. The Typer callbacks own argument
parsing, emission, polling, and exit-code mapping; everything here takes
plain arguments, returns plain data, and raises domain errors from
:mod:`mondo.api.errors`.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mondo.domain.context import ProjectionOpts


class BoardTypeFilter(StrEnum):
    """`--type` selector on `board list`.

    monday's `boards()` query returns both real boards and workdoc-backing
    boards (monday models every workdoc as a board with `type=="document"`).
    The CLI hides docs by default; pass `--type doc` to list only docs, or
    `--type all` to see everything including non-standard types such as
    `sub_items_board` and `custom_object`.
    """

    board = "board"
    doc = "doc"
    all = "all"


# Mapping from CLI filter → monday's `Board.type` server value.
_BOARD_TYPE_SERVER_VALUE: dict[BoardTypeFilter, str] = {
    BoardTypeFilter.board: "board",
    BoardTypeFilter.doc: "document",
}


def type_matches(entry: dict[str, Any], type_filter: BoardTypeFilter) -> bool:
    """Return True when `entry` should pass the `--type` filter.

    Entries cached before schema_version 2 lack `type`; we don't want those
    to silently disappear under `--type board` (the common default). The
    schema_version bump forces a one-off refresh so this branch should only
    matter in the edge case of an in-memory fetch before the cache is warm.
    Treat missing as `"board"` to keep behavior predictable.
    """
    if type_filter is BoardTypeFilter.all:
        return True
    observed = entry.get("type") or "board"
    return observed == _BOARD_TYPE_SERVER_VALUE[type_filter]


def decode_json_string_payload(value: Any) -> Any:
    """Parse monday's legacy stringified-JSON mutation payloads when possible."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def projection_wants_items_count(opts: ProjectionOpts) -> bool:
    """Skip the live `items_count` merge when the caller's projection won't
    surface it. Default behavior (no `-q`/`--fields`) returns True so the
    field stays in the emitted payload as it did pre-cache; with an explicit
    projection we only pay the round-trip if `items_count` actually appears.

    The check is intentionally lenient (substring): a JMESPath expression
    or comma-separated field list that mentions `items_count` keeps the
    merge; anything else skips it. False negatives just mean the cached
    `items_count: null` flows through — accurate per the cache contract.
    """
    needle = "items_count"
    if opts.query and needle in opts.query:
        return True
    if opts.fields and needle in opts.fields:
        return True
    return opts.query is None and opts.fields is None


def fetch_items_count(client: Any, board_id: int) -> int | None:
    """One-field live fetch for the volatile items_count field. Used to merge
    a fresh count onto a `board_details` cache hit so the cache file stays
    invalidation-free of item writes. Returns None on any unexpected shape."""
    from mondo.api.queries import BOARD_ITEMS_COUNT

    result = client.execute(BOARD_ITEMS_COUNT, variables={"ids": [board_id]})
    data = result.get("data") or {}
    boards = data.get("boards") or []
    if not boards:
        return None
    raw = boards[0].get("items_count")
    try:
        return int(raw) if raw is not None else None
    except TypeError, ValueError:
        return None
