"""Live integration tests for `mondo item list --filter`.

Regression coverage for the bug where status / dropdown filters silently
returned [] because the CLI sent labels instead of integer indices/ids in
`compare_value`. Status and dropdown values are seeded on the first item
of the `pm_board_session` fixture (see conftest.py).

Acceptance bar: server-side filter count equals the client-side
JMESPath-projected count over the unfiltered list.
"""

from __future__ import annotations

import pytest

from ._helpers import invoke, invoke_json, json_output
from .conftest import PmBoard


@pytest.mark.integration
def test_filter_status_label_returns_matching_items(pm_board_session: PmBoard) -> None:
    """`--filter <status>=<label>` must return the seeded item."""
    pm = pm_board_session
    status_col = pm.column_ids["status"]
    items = invoke_json(
        ["item", "list", "--board", str(pm.board_id), "--filter", f"{status_col}={pm.status_value}"]
    )
    matched_ids = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched_ids, (
        f"expected seeded item {pm.item_ids[0]} in filter result, got {matched_ids}"
    )
    # Every returned item really has that status.
    for it in items:
        col_values = {v["id"]: v for v in it.get("column_values") or []}
        cv = col_values.get(status_col, {})
        assert cv.get("text") == pm.status_value, (
            f"item {it['id']} returned but text={cv.get('text')!r}"
        )


@pytest.mark.integration
def test_filter_status_count_matches_client_side(pm_board_session: PmBoard) -> None:
    """count(server-filtered) == count(unfiltered ∩ status==value, client-side).

    This is the acceptance bar from the bug report: the workaround was a
    JMESPath projection over the unfiltered list. The server filter must
    agree with it.
    """
    pm = pm_board_session
    status_col = pm.column_ids["status"]

    server_filtered = invoke_json(
        ["item", "list", "--board", str(pm.board_id), "--filter", f"{status_col}={pm.status_value}"]
    )
    unfiltered = invoke_json(["item", "list", "--board", str(pm.board_id)])
    client_filtered = [
        it
        for it in unfiltered
        if any(
            v["id"] == status_col and v.get("text") == pm.status_value
            for v in it.get("column_values") or []
        )
    ]

    server_ids = sorted(int(it["id"]) for it in server_filtered)
    client_ids = sorted(int(it["id"]) for it in client_filtered)
    assert server_ids == client_ids, (
        f"server filter disagrees with client-side projection:\n"
        f"  server: {server_ids}\n"
        f"  client: {client_ids}"
    )


@pytest.mark.integration
def test_filter_status_accepts_index_syntax(pm_board_session: PmBoard) -> None:
    """`--filter <status>=#N` should work the same as `--filter <status>=<label>`.

    Cross-checks against the label form so we don't depend on the seeded
    index number.
    """
    pm = pm_board_session
    status_col = pm.column_ids["status"]

    by_label = invoke_json(
        ["item", "list", "--board", str(pm.board_id), "--filter", f"{status_col}={pm.status_value}"]
    )
    assert by_label, "label filter returned nothing — fixture seeding broken?"

    # Discover the index of the seeded label via `column labels`.
    labels = invoke_json(["column", "labels", "--board", str(pm.board_id), "--column", status_col])
    seeded = next(
        (e for e in labels if str(e.get("label")) == pm.status_value),
        None,
    )
    assert seeded is not None, f"label {pm.status_value!r} not in {labels}"
    idx = int(seeded["index"])

    by_index = invoke_json(
        ["item", "list", "--board", str(pm.board_id), "--filter", f"{status_col}=#{idx}"]
    )
    by_label_ids = sorted(int(it["id"]) for it in by_label)
    by_index_ids = sorted(int(it["id"]) for it in by_index)
    assert by_label_ids == by_index_ids


@pytest.mark.integration
def test_filter_dropdown_label_returns_matching_items(pm_board_session: PmBoard) -> None:
    """`--filter <dropdown>=<label>` must return the seeded item."""
    pm = pm_board_session
    dd_col = pm.column_ids["dropdown"]
    items = invoke_json(
        ["item", "list", "--board", str(pm.board_id), "--filter", f"{dd_col}={pm.dropdown_value}"]
    )
    matched_ids = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched_ids, (
        f"expected seeded item {pm.item_ids[0]} in dropdown filter result, got {matched_ids}"
    )


@pytest.mark.integration
def test_filter_status_not_equals_excludes_matching(pm_board_session: PmBoard) -> None:
    """`!=` should exclude items whose status matches."""
    pm = pm_board_session
    status_col = pm.column_ids["status"]
    items = invoke_json(
        [
            "item",
            "list",
            "--board",
            str(pm.board_id),
            "--filter",
            f"{status_col}!={pm.status_value}",
        ]
    )
    excluded_ids = {int(it["id"]) for it in items}
    assert pm.item_ids[0] not in excluded_ids, (
        f"item {pm.item_ids[0]} has status={pm.status_value!r} but was returned by !="
    )


@pytest.mark.integration
def test_filter_text_passthrough_still_works(pm_board_session: PmBoard) -> None:
    """Regression: text/name filters (which worked before the fix) still work."""
    pm = pm_board_session
    items = invoke_json(
        ["item", "list", "--board", str(pm.board_id), "--filter", f"name={pm.item_names[0]}"]
    )
    matched_ids = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched_ids, (
        f"name filter returned {matched_ids}, expected {pm.item_ids[0]}"
    )


@pytest.mark.integration
def test_filter_unknown_status_label_errors_cleanly(pm_board_session: PmBoard) -> None:
    """Unknown labels must hard-error with a list of known labels — the user
    chose this over silent passthrough so typos surface immediately."""
    pm = pm_board_session
    status_col = pm.column_ids["status"]
    result = invoke(
        [
            "item",
            "list",
            "--board",
            str(pm.board_id),
            "--filter",
            f"{status_col}=DefinitelyNotALabel",
        ],
        expect_exit=None,
    )
    assert result.exit_code != 0
    combined = (result.stdout or "") + (result.stderr or "")
    assert "DefinitelyNotALabel" in combined or "unknown status label" in combined.lower()
    # The seeded label should be listed among the known labels.
    assert pm.status_value in combined


# ---------------------------------------------------------------------------
# Per-column-type coverage — exercises `--filter` for every column type the
# pm_board_session fixture creates. Each test seeds a known value on
# item_ids[0] (in conftest.py) and verifies the server-side filter returns
# at least that item. Column types where monday's `any_of` operator doesn't
# work today are pinned with xfail and a short note so future contract
# changes surface as XPASS.
# ---------------------------------------------------------------------------


def _filter_matches(board_id: int, col_id: str, value: str) -> list[dict]:
    """Helper: run `--filter col=value` and return the items list."""
    return invoke_json(["item", "list", "--board", str(board_id), "--filter", f"{col_id}={value}"])


@pytest.mark.integration
def test_filter_by_text(pm_board_session: PmBoard) -> None:
    """text columns: exact, case-insensitive match via `any_of`."""
    pm = pm_board_session
    items = _filter_matches(pm.board_id, pm.column_ids["text"], pm.text_value)
    matched = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched, (
        f"text filter '{pm.text_value}' did not return item {pm.item_ids[0]}; got {matched}"
    )


@pytest.mark.integration
def test_filter_by_text_case_insensitive(pm_board_session: PmBoard) -> None:
    """monday's `any_of` matches text case-insensitively — document and pin."""
    pm = pm_board_session
    items = _filter_matches(pm.board_id, pm.column_ids["text"], pm.text_value.upper())
    matched = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched, (
        f"case-insensitive match failed: {pm.text_value.upper()!r} → {matched}"
    )


@pytest.mark.integration
def test_filter_by_long_text(pm_board_session: PmBoard) -> None:
    """long_text columns: exact match on the full value."""
    pm = pm_board_session
    items = _filter_matches(pm.board_id, pm.column_ids["long_text"], pm.long_text_value)
    matched = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched, (
        f"long_text filter did not return item {pm.item_ids[0]}; got {matched}"
    )


@pytest.mark.integration
def test_filter_by_numbers(pm_board_session: PmBoard) -> None:
    """numbers columns: pass the value as a string (monday accepts it)."""
    pm = pm_board_session
    items = _filter_matches(pm.board_id, pm.column_ids["numbers"], pm.numbers_value)
    matched = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched, (
        f"numbers filter '{pm.numbers_value}' did not return item {pm.item_ids[0]}; got {matched}"
    )


@pytest.mark.integration
def test_filter_by_name(pm_board_session: PmBoard) -> None:
    """name (the item-name pseudo-column) supports exact-match `any_of`."""
    pm = pm_board_session
    items = _filter_matches(pm.board_id, "name", pm.item_names[0])
    matched = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched


@pytest.mark.integration
@pytest.mark.xfail(
    reason=(
        "Monday's `items_page` does not support `any_of` on date columns. "
        "The CLI's --filter syntax maps `=` to `any_of`; a separate change "
        "would need to wire `between`/`greater_than`/`lower_than` operators "
        "before date filtering works. Verified empirically 2026-05-18."
    ),
    strict=True,
)
def test_filter_by_date(pm_board_session: PmBoard) -> None:
    pm = pm_board_session
    items = _filter_matches(pm.board_id, pm.column_ids["date"], pm.date_value)
    matched = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched


@pytest.mark.integration
@pytest.mark.xfail(
    reason=(
        "people columns: monday does not match `any_of` against user-id "
        "strings sent by the default CLI path. A dedicated filter codec "
        "would need to emit integer ids (and possibly `compare_attribute: "
        "'person'`). Verified empirically 2026-05-18."
    ),
    strict=True,
)
def test_filter_by_person(pm_board_session: PmBoard) -> None:
    pm = pm_board_session
    items = _filter_matches(pm.board_id, pm.column_ids["person"], str(pm.person_id))
    matched = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched


@pytest.mark.integration
@pytest.mark.xfail(
    reason=(
        "timeline columns expect `between`/range operators, not `any_of` "
        "with a `YYYY-MM-DD..YYYY-MM-DD` string. Out of scope for the "
        "status/dropdown bug fix; track separately."
    ),
    strict=True,
)
def test_filter_by_timeline(pm_board_session: PmBoard) -> None:
    pm = pm_board_session
    # The fixture leaves timeline unset; the call should still succeed but
    # return zero matches today. Strict xfail means this passes if monday
    # ever starts matching this shape.
    items = _filter_matches(pm.board_id, pm.column_ids["timeline"], "2026-04-01..2026-04-30")
    matched = {int(it["id"]) for it in items}
    assert pm.item_ids[0] in matched


@pytest.mark.integration
def test_filter_doc_column_rejected(pm_board_session: PmBoard) -> None:
    """doc columns aren't filterable — monday returns an error or 0 results.

    We don't crash; the CLI just hands the server's response back. Document
    the current behavior so it doesn't drift unnoticed.
    """
    pm = pm_board_session
    result = invoke(
        [
            "item",
            "list",
            "--board",
            str(pm.board_id),
            "--filter",
            f"{pm.column_ids['doc']}=anything",
        ],
        expect_exit=None,
    )
    # Either monday returns 0 items with exit 0, or it raises an
    # InvalidColumnTypeException with non-zero exit. Both outcomes are
    # acceptable for this regression guard — we just verify we don't
    # silently match the seeded item by mistake.
    if result.exit_code == 0:
        items = json_output(result)
        assert pm.item_ids[0] not in {int(it["id"]) for it in items}
