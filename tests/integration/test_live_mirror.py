"""Live two-board mirror / board_relation coverage (#105 follow-up).

Builds a self-provisioning fixture entirely via the API: a source board
with a text column + item, and a consumer board with a `board_relation`
pointing at it plus a **configured** `mirror` reflecting the source text
column through that relation.

Why this exists: monday returns `text: null` for computed columns — the
value lives in the polymorphic `display_value`, and mondo fills `text`
from it on typed reads. Unit tests mock that payload; this file proves
the whole chain against the live API, which is the part most likely to
drift when the pinned API version bumps.

API gotcha this fixture also guards: the mirror `defaults` **write**
shape (`{"settings": {"relation_column": {...}, "displayed_linked_columns":
[{"board_id": ..., "column_ids": [...]}]}}`, array-of-objects) differs
from the `settings_str` **read** shape (a board-id → column-ids map), and
a malformed `defaults` is silently ignored — the column is created
unconfigured with no error. `get_column_type_schema(type: mirror)` is the
authoritative source for the write shape.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from ._helpers import CleanupPlan, invoke_json, run_cleanup, wait_for

_SRC_TEXT_COL = "e2e_email"
_REL_COL = "e2e_rel"
_MIRROR_COL = "e2e_mir"
_EMAIL = "alice@e2e.test"


@dataclass(frozen=True)
class MirrorBoards:
    src_board_id: int
    dst_board_id: int
    src_item_id: int
    dst_item_id: int


@pytest.fixture(scope="module")
def mirror_boards(session_env: int) -> Iterator[MirrorBoards]:
    """Source board + consumer board with a configured mirror, built via API.

    Module-scoped so all tests share one build; both boards are
    hard-deleted at module end (consumer first, then source).
    """
    workspace_id = session_env
    suffix = uuid.uuid4().hex[:8]
    plan = CleanupPlan()

    try:
        src = invoke_json(
            [
                "board",
                "create",
                "--name",
                f"E2E Mirror Src {suffix}",
                "--workspace",
                str(workspace_id),
            ]
        )
        src_board_id = int(src["id"])
        plan.add(
            f"mirror src board {src_board_id}",
            "board",
            "delete",
            "--id",
            str(src_board_id),
            "--hard",
        )

        dst = invoke_json(
            [
                "board",
                "create",
                "--name",
                f"E2E Mirror Dst {suffix}",
                "--workspace",
                str(workspace_id),
            ]
        )
        dst_board_id = int(dst["id"])
        plan.add(
            f"mirror dst board {dst_board_id}",
            "board",
            "delete",
            "--id",
            str(dst_board_id),
            "--hard",
        )

        invoke_json(
            [
                "column",
                "create",
                "--board",
                str(src_board_id),
                "--title",
                "E2E Email",
                "--type",
                "text",
                "--id",
                _SRC_TEXT_COL,
            ]
        )
        src_item = invoke_json(
            [
                "item",
                "create",
                "--board",
                str(src_board_id),
                "--name",
                f"E2E Mirror Alice {suffix}",
                "--column",
                f"{_SRC_TEXT_COL}={_EMAIL}",
            ]
        )
        src_item_id = int(src_item["id"])

        invoke_json(
            [
                "column",
                "create",
                "--board",
                str(dst_board_id),
                "--title",
                "E2E Link",
                "--type",
                "board_relation",
                "--id",
                _REL_COL,
                "--defaults",
                json.dumps({"boardIds": [src_board_id]}),
            ]
        )
        # The write shape: `settings`-wrapped, displayed_linked_columns as an
        # ARRAY of {board_id, column_ids}. The map shape settings_str reads
        # back is silently ignored here — see module docstring.
        invoke_json(
            [
                "column",
                "create",
                "--board",
                str(dst_board_id),
                "--title",
                "E2E Mirror Email",
                "--type",
                "mirror",
                "--id",
                _MIRROR_COL,
                "--defaults",
                json.dumps(
                    {
                        "settings": {
                            "relation_column": {_REL_COL: True},
                            "displayed_linked_columns": [
                                {
                                    "board_id": str(src_board_id),
                                    "column_ids": [_SRC_TEXT_COL],
                                }
                            ],
                        }
                    }
                ),
            ]
        )

        dst_item = invoke_json(
            [
                "item",
                "create",
                "--board",
                str(dst_board_id),
                "--name",
                f"E2E Mirror Row {suffix}",
                "--column",
                f"{_REL_COL}={src_item_id}",
            ]
        )
        dst_item_id = int(dst_item["id"])

        yield MirrorBoards(
            src_board_id=src_board_id,
            dst_board_id=dst_board_id,
            src_item_id=src_item_id,
            dst_item_id=dst_item_id,
        )
    finally:
        run_cleanup(plan)


def _dst_column_values(boards: MirrorBoards) -> dict[str, dict[str, Any]]:
    rows = invoke_json(
        [
            "item",
            "list",
            "--board",
            str(boards.dst_board_id),
            "--columns",
            f"{_REL_COL},{_MIRROR_COL}",
            "--no-cache",
        ]
    )
    # `board create` without --empty ships default placeholder items — pick
    # the linked row by id, never rows[0].
    row = next((r for r in rows if str(r.get("id")) == str(boards.dst_item_id)), None)
    assert row is not None, f"item {boards.dst_item_id} not in board listing"
    return {cv["id"]: cv for cv in row.get("column_values") or []}


@pytest.mark.integration
def test_live_mirror_settings_took(mirror_boards: MirrorBoards) -> None:
    """The configured-create actually configured the mirror (guards against
    monday changing the defaults write shape and reverting to silent-ignore)."""
    meta = invoke_json(
        [
            "column",
            "get-meta",
            "--board",
            str(mirror_boards.dst_board_id),
            "--column",
            _MIRROR_COL,
            "--no-cache",
        ]
    )
    settings = json.loads(meta.get("settings_str") or "{}")
    assert settings.get("relation_column") == {_REL_COL: True}, settings
    assert settings.get("displayed_linked_columns") == {
        str(mirror_boards.src_board_id): [_SRC_TEXT_COL]
    }, settings


@pytest.mark.integration
def test_live_mirror_display_value_flows_and_fills_text(mirror_boards: MirrorBoards) -> None:
    """The mirrored value arrives in `display_value` and typed reads fill
    `text` from it (the #105 fallback), for the mirror and the relation."""

    def _mirror_populated() -> dict[str, dict[str, Any]]:
        values = _dst_column_values(mirror_boards)
        assert values.get(_MIRROR_COL, {}).get("display_value"), (
            f"mirror display_value not propagated yet: {values.get(_MIRROR_COL)}"
        )
        return values

    # Propagation into items_page is asynchronous and can lag the direct
    # single-item read by minutes on a slow day — be generous.
    values = wait_for("mirror display_value to propagate", _mirror_populated, timeout_seconds=240.0)

    mirror = values[_MIRROR_COL]
    assert mirror["display_value"] == _EMAIL
    assert mirror["text"] == _EMAIL  # filled from display_value

    relation = values[_REL_COL]
    assert relation["display_value"]  # linked item's name
    assert relation["text"] == relation["display_value"]
    linked = relation.get("linked_item_ids") or []
    assert str(mirror_boards.src_item_id) in [str(i) for i in linked], relation


@pytest.mark.integration
def test_live_mirror_item_get_fills_text(mirror_boards: MirrorBoards) -> None:
    """`item get` runs the same fill as `item list`. Polls its own read so the
    test holds under random ordering / solo runs."""

    def _mirror_filled() -> None:
        got = invoke_json(["item", "get", "--id", str(mirror_boards.dst_item_id), "--no-cache"])
        values = {cv["id"]: cv for cv in got.get("column_values") or []}
        mirror = values[_MIRROR_COL]
        assert mirror.get("display_value") == _EMAIL, f"not propagated yet: {mirror}"
        assert mirror["text"] == _EMAIL

    wait_for("item get to carry the filled mirror text", _mirror_filled, timeout_seconds=240.0)


@pytest.mark.integration
def test_live_mirror_column_get_renders(mirror_boards: MirrorBoards) -> None:
    """Non-raw `column get` renders the mirrored display_value."""

    def _rendered() -> Any:
        rendered = invoke_json(
            [
                "column",
                "get",
                "--item",
                str(mirror_boards.dst_item_id),
                "--column",
                _MIRROR_COL,
            ]
        )
        assert rendered == _EMAIL, f"expected rendered mirror {_EMAIL!r}, got {rendered!r}"
        return rendered

    wait_for("column get to render the mirrored value", _rendered, timeout_seconds=240.0)


@pytest.mark.integration
def test_live_filter_on_mirror_refused_client_side(mirror_boards: MirrorBoards) -> None:
    """`--filter` on a mirror column exits 2 with guidance before any items
    request (#109) — previously monday's opaque InvalidColumnTypeException."""
    from ._helpers import invoke

    result = invoke(
        [
            "item",
            "list",
            "--board",
            str(mirror_boards.dst_board_id),
            "--filter",
            f"{_MIRROR_COL}=whatever",
        ],
        expect_exit=2,
    )
    assert "cannot filter on mirror" in (result.stderr or "") + (result.output or "")


@pytest.mark.integration
def test_live_filter_on_board_relation_matches_by_item_id(mirror_boards: MirrorBoards) -> None:
    """`--filter <relation>=<item_id>` filters server-side with INTEGER ids
    (string ids match nothing — codex review finding on the relation codec)."""

    def _row_found() -> None:
        rows = invoke_json(
            [
                "item",
                "list",
                "--board",
                str(mirror_boards.dst_board_id),
                "--filter",
                f"{_REL_COL}={mirror_boards.src_item_id}",
                "--no-cache",
            ]
        )
        assert [r["id"] for r in rows] == [str(mirror_boards.dst_item_id)], rows

    wait_for("board_relation filter to match the linked row", _row_found, timeout_seconds=240.0)
