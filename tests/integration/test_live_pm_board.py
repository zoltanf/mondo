"""Project-management board lifecycle against the live API.

Builds a realistic PM board once per session via `pm_board_session`,
then exercises read paths (CLI listing/get/filter), JSON export, CSV
export-then-import round-trip, and markdown export smoke check.
"""

from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from ._helpers import (
    CleanupPlan,
    format_failure,
    invoke,
    invoke_json,
    json_output,
    wait_for,
)
from .conftest import PmBoard


@pytest.mark.integration
def test_live_pm_board_setup_visible_via_cli(pm_board_session: PmBoard) -> None:
    """Verify the session PM board reads back through the CLI exactly as built."""
    pm = pm_board_session

    # board get
    board = invoke_json(["board", "get", "--id", str(pm.board_id)])
    assert int(board["id"]) == pm.board_id
    assert board["name"].startswith("E2E PM Board")
    assert int(board["folder_id"]) == pm.folder_id

    # group list — all 3 groups present
    groups = invoke_json(["group", "list", "--board", str(pm.board_id)])
    visible_group_ids = {g["id"] for g in groups}
    for logical, gid in pm.group_ids.items():
        assert gid in visible_group_ids, f"group {logical}={gid} missing"

    # column list — all 8 columns present and types match (people alias accepted).
    columns = invoke_json(["column", "list", "--board", str(pm.board_id)])
    by_id = {c["id"]: c for c in columns}
    expected_types = {
        pm.column_ids["status"]: "status",
        pm.column_ids["person"]: "people",
        pm.column_ids["date"]: "date",
        pm.column_ids["timeline"]: "timeline",
        pm.column_ids["numbers"]: "numbers",
        pm.column_ids["text"]: "text",
        pm.column_ids["long_text"]: "long_text",
        pm.column_ids["doc"]: "doc",
    }
    for col_id, expected_type in expected_types.items():
        assert col_id in by_id, f"column {col_id} not visible"
        actual_type = by_id[col_id]["type"]
        if expected_type == "people":
            assert actual_type in {"people", "person"}, f"col {col_id} type={actual_type}"
        else:
            assert actual_type == expected_type, f"col {col_id} type={actual_type}, want {expected_type}"

    # item list — all 5 fixture items visible
    items = invoke_json(["item", "list", "--board", str(pm.board_id)])
    seen_ids = {int(i["id"]) for i in items}
    for iid in pm.item_ids:
        assert iid in seen_ids, f"item {iid} not visible"

    # item get — group membership + a column value match the fixture
    sample = invoke_json(["item", "get", "--id", str(pm.item_ids[0])])
    assert sample["name"] == pm.item_names[0]
    assert sample["group"]["id"] == pm.group_ids["backlog"]
    values = {v["id"]: v for v in sample.get("column_values") or []}
    assert pm.column_ids["text"] in values
    assert values[pm.column_ids["text"]]["text"] == "design@e2e.test"


@pytest.mark.integration
def test_live_pm_board_export_json_matches_source(pm_board_session: PmBoard) -> None:
    """`mondo export board --format json` reflects items + groups + values."""
    pm = pm_board_session
    result = invoke(
        ["export", "board", str(pm.board_id), "--format", "json"],
        expect_exit=0,
    )
    payload = json.loads(result.stdout)

    items = _extract_items_from_export(payload)
    item_names = {it["name"] for it in items}
    for expected in pm.item_names:
        assert expected in item_names, f"export missing item {expected!r}: {item_names}"

    seen_group_titles = _extract_group_titles_from_export(payload, items)
    for expected_title in {"Backlog", "In Progress", "Done"}:
        assert expected_title in seen_group_titles, (
            f"export missing group {expected_title!r}: {seen_group_titles}"
        )

    # Verify the long_text value for one known item round-trips.
    target_item = next(it for it in items if it["name"] == pm.item_names[0])
    flat = _flatten_item_columns(target_item)
    assert "Initial spec for login + 2FA." in str(flat), (
        f"long_text value not in export for {pm.item_names[0]!r}: {flat}"
    )


@pytest.mark.integration
def test_live_pm_board_export_csv_then_import_into_fresh_board(
    pm_board_session: PmBoard,
    cleanup_plan: CleanupPlan,
    tmp_path: Path,
) -> None:
    """Export to CSV, import into a fresh board, verify name + text + numbers round-trip."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]

    # 1. Export the session board as CSV.
    csv_path = tmp_path / "pm_export.csv"
    invoke(
        [
            "export", "board", str(pm.board_id),
            "--format", "csv",
            "--out", str(csv_path),
        ],
        expect_exit=0,
    )
    assert csv_path.exists() and csv_path.stat().st_size > 0, "csv export empty"

    rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines()))
    assert len(rows) >= 5, f"export CSV has {len(rows)} rows; expected >=5"

    # 2. Build a fresh board.
    fresh_board = invoke_json(
        [
            "board", "create",
            "--workspace", str(pm.workspace_id),
            "--name", f"E2E PM Import {suffix}",
            "--kind", "private",
            "--empty",
        ]
    )
    fresh_board_id = int(fresh_board["id"])
    cleanup_plan.add(
        f"fresh board {fresh_board_id}",
        "board", "delete", "--id", str(fresh_board_id), "--hard",
    )

    # Need at least one group as the import target; --empty boards may have none.
    fresh_group = invoke_json(
        [
            "group", "create",
            "--board", str(fresh_board_id),
            "--name", "Imported",
        ]
    )
    fresh_group_id = fresh_group["id"]

    # Recreate the simple-typed columns whose titles match the export's headers.
    invoke_json(
        [
            "column", "create",
            "--board", str(fresh_board_id),
            "--title", "Owner Email",
            "--type", "text",
            "--id", "text_owner_email",
        ]
    )
    invoke_json(
        [
            "column", "create",
            "--board", str(fresh_board_id),
            "--title", "Story Points",
            "--type", "numbers",
            "--id", "numbers_story_points",
        ]
    )
    invoke_json(
        [
            "column", "create",
            "--board", str(fresh_board_id),
            "--title", "Description",
            "--type", "long_text",
            "--id", "long_text_description",
        ]
    )

    # 3. Run import. The export stores group *titles* under the `group` column,
    # which monday's import reads as group IDs — so we override --group-column
    # to a header that doesn't exist (suppressing the per-row group lookup) and
    # supply --group <fresh_group_id> as the default for every row.
    import_result = invoke(
        [
            "import", "board", str(fresh_board_id),
            "--from", str(csv_path),
            "--group", fresh_group_id,
            "--group-column", "__nogroup__",
        ],
        expect_exit=None,
    )
    assert import_result.exit_code in {0, 1}, format_failure(["import board"], import_result)
    envelope = json_output(import_result)
    assert envelope["summary"]["created"] >= 5, envelope

    def _items_landed() -> list[dict[str, Any]]:
        items = invoke_json(["item", "list", "--board", str(fresh_board_id)])
        assert len(items) >= 5, f"only {len(items)} items landed"
        return items

    items = wait_for("imported items visible", _items_landed)

    # 4. Assertions: names match (set-equality), text + numbers for one known
    # item round-tripped. Status/dropdown/people values are not asserted.
    imported_names = {i["name"] for i in items}
    for expected in pm.item_names:
        assert expected in imported_names, f"imported board missing {expected!r}: {imported_names}"

    ship_id = next(int(i["id"]) for i in items if i["name"] == "Ship v2 launch")
    detailed = invoke_json(["item", "get", "--id", str(ship_id)])
    values = {v["id"]: v for v in detailed.get("column_values") or []}
    text_val = values.get("text_owner_email", {}).get("text", "")
    numbers_val = values.get("numbers_story_points", {}).get("text", "")
    assert "pm@e2e.test" in text_val, f"text column not round-tripped: {text_val!r}"
    assert numbers_val.replace(".0", "") == "13", f"numbers column not round-tripped: {numbers_val!r}"


@pytest.mark.integration
def test_live_pm_board_export_markdown_smoke(pm_board_session: PmBoard) -> None:
    """`mondo export board --format md` produces non-empty markdown mentioning items."""
    pm = pm_board_session
    result = invoke(
        ["export", "board", str(pm.board_id), "--format", "md"],
        expect_exit=0,
    )
    md = result.stdout
    assert md.strip(), "markdown export empty"

    for item_name in pm.item_names:
        assert item_name in md, f"item {item_name!r} not in markdown export"
    # Group titles also surface (the GFM table includes a `group` column).
    for group_title in ("Backlog", "In Progress", "Done"):
        assert group_title in md, f"group {group_title!r} not in markdown export"


# ---------------------------------------------------------------------------
# Helpers private to this file
# ---------------------------------------------------------------------------


def _extract_items_from_export(payload: Any) -> list[dict[str, Any]]:
    """Find the items list inside a JSON export payload (tolerates a couple of shapes)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "data", "results"):
            if key in payload and isinstance(payload[key], list):
                return payload[key]
        if "board" in payload and isinstance(payload["board"], dict):
            inner = payload["board"].get("items") or payload["board"].get("items_page", {}).get("items")
            if isinstance(inner, list):
                return inner
    raise AssertionError(
        "could not find items in export payload: "
        f"keys={list(payload.keys()) if isinstance(payload, dict) else type(payload)}"
    )


def _extract_group_titles_from_export(payload: Any, items: list[dict[str, Any]]) -> set[str]:
    titles: set[str] = set()
    for it in items:
        # CSV export flattens `group` into the row as a title string. JSON
        # export also includes it as a top-level field (string title).
        group_field = it.get("group")
        if isinstance(group_field, str) and group_field:
            titles.add(group_field)
        elif isinstance(group_field, dict) and group_field.get("title"):
            titles.add(group_field["title"])
    if isinstance(payload, dict):
        groups = payload.get("groups") or payload.get("board", {}).get("groups")
        if isinstance(groups, list):
            for g in groups:
                if isinstance(g, dict) and g.get("title"):
                    titles.add(g["title"])
    return titles


def _flatten_item_columns(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"name": item.get("name")}
    # JSON export: the row has top-level keys for each column TITLE.
    for key, value in item.items():
        if key in {"id", "name", "state", "group"}:
            continue
        out[key] = value
    return out
