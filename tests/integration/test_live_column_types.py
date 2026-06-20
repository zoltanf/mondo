"""Live integration tests for the column-value codec registry.

The session PM board only exercises a handful of column types
(status / dropdown / people / date / numbers / text / long_text). This
file builds a dedicated scratch board carrying one column of every other
*writable* type, then round-trips a value through each codec via
`column set` + `item get`.

Cross-referencing codecs (`board_relation`, `dependency`) need real
target item ids and a configured connect-boards column, which a freshly
created column doesn't carry — those are covered via `--dry-run`, which
proves the codec expansion without depending on board wiring.

Also covers the column-metadata commands that have no other live test:
`column get-meta`, `column change-metadata`, `column rename`,
`column clear`, `column set-many`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from ._helpers import CleanupPlan, invoke_json, run_cleanup, wait_for

# (logical name, monday column type) for every writable scalar codec not
# already exercised by the session PM board.
_SCALAR_COLUMN_TYPES: list[tuple[str, str]] = [
    ("checkbox", "checkbox"),
    ("rating", "rating"),
    ("email", "email"),
    ("phone", "phone"),
    ("link", "link"),
    ("country", "country"),
    ("world_clock", "world_clock"),
    ("week", "week"),
    ("hour", "hour"),
    ("timeline", "timeline"),
    ("location", "location"),
    ("tags", "tags"),
]

# logical -> (shorthand value passed to `column set`, substring expected to
# survive the round-trip in the column's text or raw value).
_CODEC_CASES: dict[str, tuple[str, str]] = {
    "checkbox": ("true", "true"),
    "rating": ("4", "4"),
    "email": ('round@e2e.test,"Round Trip"', "round@e2e.test"),
    "phone": ("+19175550123,US", "9175550123"),
    "link": ('https://example.com,"click me"', "example.com"),
    "country": ("US", "US"),
    "world_clock": ("Europe/London", "Europe/London"),
    "week": ("2026-W16", "2026"),
    "hour": ("14:30", "14"),
    "timeline": ("2026-04-01..2026-04-15", "2026-04-01"),
    "location": ('40.68,-74.04,"NYC"', "40.68"),
    "tags": ("e2eroundtrip", "e2eroundtrip"),
}


@dataclass(frozen=True)
class TypesBoard:
    board_id: int
    group_id: str
    item_id: int
    column_ids: dict[str, str]  # logical -> column id


@pytest.fixture(scope="module")
def types_board(session_env: int) -> Iterator[TypesBoard]:
    """Build a scratch board with one column per writable codec + one item.

    Module-scoped so all the parametrized round-trips share a single
    board build; torn down (hard-deleted) at module end.
    """
    workspace_id = session_env
    suffix = uuid.uuid4().hex[:8]
    plan = CleanupPlan()

    board = invoke_json(
        [
            "board",
            "create",
            "--name",
            f"E2E Column Types {suffix}",
            "--workspace",
            str(workspace_id),
        ]
    )
    board_id = int(board["id"])
    plan.add(f"types board {board_id}", "board", "delete", "--id", str(board_id), "--hard")

    column_ids: dict[str, str] = {}
    for logical, col_type in [
        *_SCALAR_COLUMN_TYPES,
        ("board_relation", "board_relation"),
        ("dependency", "dependency"),
    ]:
        created = invoke_json(
            [
                "column",
                "create",
                "--board",
                str(board_id),
                "--title",
                f"E2E {logical}",
                "--type",
                col_type,
                "--id",
                f"e2e_{logical}",
            ]
        )
        column_ids[logical] = created["id"]

    group = invoke_json(["group", "list", "--board", str(board_id)])[0]
    group_id = group["id"]
    item = invoke_json(
        [
            "item",
            "create",
            "--board",
            str(board_id),
            "--group",
            group_id,
            "--name",
            f"E2E Types Item {suffix}",
        ]
    )
    item_id = int(item["id"])

    try:
        yield TypesBoard(
            board_id=board_id,
            group_id=group_id,
            item_id=item_id,
            column_ids=column_ids,
        )
    finally:
        run_cleanup(plan)


def _column_value(item_id: int, column_id: str) -> dict[str, Any]:
    got = invoke_json(["item", "get", "--id", str(item_id)])
    cv = {v["id"]: v for v in got.get("column_values") or []}
    return cv.get(column_id) or {}


@pytest.mark.integration
@pytest.mark.parametrize("logical", list(_CODEC_CASES))
def test_live_column_codec_roundtrip(types_board: TypesBoard, logical: str) -> None:
    """Each scalar codec: `column set <shorthand>` then read the value back."""
    value, expected = _CODEC_CASES[logical]
    column_id = types_board.column_ids[logical]

    args = [
        "column",
        "set",
        "--item",
        str(types_board.item_id),
        "--column",
        column_id,
        "--value",
        value,
    ]
    # tags resolves names via create_or_get_tag, which needs label creation.
    if logical == "tags":
        args.append("--create-labels-if-missing")
    invoke_json(args)

    def _landed() -> None:
        col = _column_value(types_board.item_id, column_id)
        haystack = f"{col.get('text') or ''}\n{col.get('value') or ''}"
        assert expected in haystack, f"{logical}: {expected!r} not in {haystack!r}"

    wait_for(f"{logical} value landed", _landed)


@pytest.mark.integration
@pytest.mark.parametrize("logical", ["board_relation", "dependency"])
def test_live_connect_codec_dry_run(types_board: TypesBoard, logical: str) -> None:
    """`board_relation`/`dependency` codecs expand a CSV of ids into
    {"item_ids": [...]} — asserted via --dry-run (no real wiring needed)."""
    column_id = types_board.column_ids[logical]
    result = invoke_json(
        [
            "--dry-run",
            "column",
            "set",
            "--item",
            str(types_board.item_id),
            "--column",
            column_id,
            "--value",
            "12345,67890",
        ]
    )
    payload = json.dumps(result)
    assert "12345" in payload and "67890" in payload, payload
    assert "item_ids" in payload, f"codec did not expand to item_ids: {payload}"


@pytest.mark.integration
def test_live_column_get_meta(types_board: TypesBoard) -> None:
    """`column get-meta` returns one column with `settings_str` preserved."""
    column_id = types_board.column_ids["rating"]
    meta = invoke_json(
        ["column", "get-meta", "--board", str(types_board.board_id), "--column", column_id]
    )
    assert meta["id"] == column_id
    assert meta["type"] == "rating"
    assert "settings_str" in meta


@pytest.mark.integration
def test_live_column_change_metadata_and_rename(types_board: TypesBoard) -> None:
    """`column change-metadata --property title` and the `column rename` alias."""
    column_id = types_board.column_ids["email"]
    new_desc = f"desc {uuid.uuid4().hex[:6]}"
    invoke_json(
        [
            "column",
            "change-metadata",
            "--board",
            str(types_board.board_id),
            "--column",
            column_id,
            "--property",
            "description",
            "--value",
            new_desc,
        ]
    )

    new_title = f"E2E Renamed {uuid.uuid4().hex[:6]}"
    invoke_json(
        [
            "column",
            "rename",
            "--board",
            str(types_board.board_id),
            "--column",
            column_id,
            "--title",
            new_title,
        ]
    )

    def _renamed() -> None:
        cols = invoke_json(["column", "list", "--board", str(types_board.board_id)])
        by_id = {c["id"]: c for c in cols}
        assert by_id[column_id]["title"] == new_title

    wait_for("column renamed", _renamed)


@pytest.mark.integration
def test_live_column_set_many_then_clear(types_board: TypesBoard) -> None:
    """`column set-many` writes several columns in one mutation; `column clear`
    blanks one back out."""
    checkbox_id = types_board.column_ids["checkbox"]
    rating_id = types_board.column_ids["rating"]
    values = json.dumps({checkbox_id: {"checked": "true"}, rating_id: {"rating": 5}})
    invoke_json(["column", "set-many", "--item", str(types_board.item_id), "--values", values])

    def _both_set() -> None:
        rating = _column_value(types_board.item_id, rating_id)
        assert "5" in f"{rating.get('text') or ''}\n{rating.get('value') or ''}"

    wait_for("set-many landed", _both_set)

    invoke_json(["column", "clear", "--item", str(types_board.item_id), "--column", rating_id])

    def _cleared() -> None:
        rating = _column_value(types_board.item_id, rating_id)
        raw = rating.get("value") or ""
        # monday leaves a `{"changed_at": ...}` stub after clearing; the
        # substantive `rating` key is what must be gone.
        assert not (rating.get("text") or "").strip(), f"rating text remained: {rating!r}"
        assert '"rating"' not in raw, f"rating value not cleared: {raw!r}"

    wait_for("column cleared", _cleared)
