"""Live integration tests for `mondo column doc` set/get/append/clear."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from ._helpers import (
    CleanupPlan,
    invoke,
    invoke_json,
    wait_for,
)
from .conftest import PmBoard

FIXTURES = Path(__file__).parent / "fixtures" / "doc_roundtrip"


def _scratch_item_on_pm_board(
    pm: PmBoard,
    cleanup_plan: CleanupPlan,
    suffix: str,
) -> int:
    item = invoke_json(
        [
            "item", "create",
            "--board", str(pm.board_id),
            "--group", pm.group_ids["backlog"],
            "--name", f"E2E Doc-Col Item {suffix}",
        ]
    )
    item_id = int(item["id"])
    cleanup_plan.add(
        f"doc-col scratch {item_id}",
        "item", "delete", "--id", str(item_id), "--hard",
    )
    return item_id


def _read_md(item_id: int, column_id: str) -> str:
    result = invoke(
        [
            "column", "doc", "get",
            "--item", str(item_id),
            "--column", column_id,
            "--format", "markdown",
        ],
        expect_exit=0,
    )
    return result.stdout


@pytest.mark.integration
def test_live_doc_column_set_from_markdown_and_read_back(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """`column doc set --from-file` then `column doc get` round-trips supported markdown."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    item_id = _scratch_item_on_pm_board(pm, cleanup_plan, suffix)
    doc_col = pm.column_ids["doc"]
    strict_path = FIXTURES / "strict_input.md"

    invoke_json(
        [
            "column", "doc", "set",
            "--item", str(item_id),
            "--column", doc_col,
            "--from-file", str(strict_path),
        ]
    )

    def _content_landed() -> str:
        md = _read_md(item_id, doc_col)
        # The exporter adds a leading title block ("Spec Doc: ...") plus the
        # rendered markdown. Spot-check that distinctive lines made it through.
        assert "Section A" in md, f"missing 'Section A' in: {md[:400]}"
        assert "Section B" in md, f"missing 'Section B' in: {md[:400]}"
        assert "bullet item one" in md, f"missing list item in: {md[:400]}"
        assert "first numbered step" in md, f"missing numbered step: {md[:400]}"
        return md

    wait_for("doc column content landed", _content_landed)


@pytest.mark.integration
def test_live_doc_column_append_adds_blocks(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """`column doc append` adds new content alongside existing blocks."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    item_id = _scratch_item_on_pm_board(pm, cleanup_plan, suffix)
    doc_col = pm.column_ids["doc"]
    strict_path = FIXTURES / "strict_input.md"
    append_path = FIXTURES / "append_input.md"

    invoke_json(
        [
            "column", "doc", "set",
            "--item", str(item_id),
            "--column", doc_col,
            "--from-file", str(strict_path),
        ]
    )

    def _initial_landed() -> None:
        assert "Section A" in _read_md(item_id, doc_col)

    wait_for("initial content landed", _initial_landed)

    invoke_json(
        [
            "column", "doc", "append",
            "--item", str(item_id),
            "--column", doc_col,
            "--from-file", str(append_path),
        ]
    )

    def _appended_landed() -> str:
        md = _read_md(item_id, doc_col)
        assert "Appended section" in md, f"appended heading missing: {md[-400:]}"
        assert "appended bullet" in md, f"appended bullet missing: {md[-400:]}"
        # Original content must still be present.
        assert "Section A" in md, "original content lost on append"
        # Order: original Section A appears before appended heading.
        idx_orig = md.find("Section A")
        idx_appended = md.find("Appended section")
        assert idx_orig < idx_appended, (
            f"appended block landed before original content: orig={idx_orig}, app={idx_appended}"
        )
        return md

    wait_for("appended content landed", _appended_landed)


@pytest.mark.integration
def test_live_doc_column_clear_unlinks(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """`column doc clear` unlinks the doc column without erroring."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    item_id = _scratch_item_on_pm_board(pm, cleanup_plan, suffix)
    doc_col = pm.column_ids["doc"]

    invoke_json(
        [
            "column", "doc", "set",
            "--item", str(item_id),
            "--column", doc_col,
            "--markdown", "## Will be cleared\n\nbody.\n",
        ]
    )

    def _content_visible() -> None:
        assert "Will be cleared" in _read_md(item_id, doc_col)

    wait_for("doc column populated", _content_visible)

    invoke_json(
        [
            "column", "doc", "clear",
            "--item", str(item_id),
            "--column", doc_col,
        ]
    )

    def _cleared() -> str:
        # After clear, the column has no linked doc. `get` should either
        # return empty markdown or fail gracefully; either is acceptable
        # as long as the prior content is gone.
        result = invoke(
            [
                "column", "doc", "get",
                "--item", str(item_id),
                "--column", doc_col,
                "--format", "markdown",
            ],
            expect_exit=None,
        )
        if result.exit_code == 0:
            md = result.stdout
            assert "Will be cleared" not in md, f"cleared content still visible: {md[:200]}"
            return md
        # Non-zero exit is also fine after a clear (no doc to fetch).
        assert result.exit_code in {1, 6}, f"unexpected exit: {result.exit_code}"
        return ""

    wait_for("doc column cleared", _cleared)


@pytest.mark.integration
def test_live_doc_column_set_from_stdin(
    pm_board_session: PmBoard, cleanup_plan: CleanupPlan
) -> None:
    """`column doc set --from-stdin` reads markdown from stdin."""
    pm = pm_board_session
    suffix = uuid.uuid4().hex[:8]
    item_id = _scratch_item_on_pm_board(pm, cleanup_plan, suffix)
    doc_col = pm.column_ids["doc"]
    body = "# From stdin\n\nstdin paragraph body.\n\n- stdin bullet\n"

    invoke_json(
        [
            "column", "doc", "set",
            "--item", str(item_id),
            "--column", doc_col,
            "--from-stdin",
        ],
        input=body,
    )

    def _stdin_landed() -> str:
        md = _read_md(item_id, doc_col)
        assert "From stdin" in md, f"stdin heading missing: {md[:400]}"
        assert "stdin paragraph body" in md, f"stdin paragraph missing: {md[:400]}"
        assert "stdin bullet" in md, f"stdin bullet missing: {md[:400]}"
        return md

    wait_for("stdin content landed", _stdin_landed)
