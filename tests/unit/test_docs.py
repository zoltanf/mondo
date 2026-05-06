"""Tests for mondo.docs — doc column value parsing + markdown converters."""

from __future__ import annotations

import pytest

from mondo.docs import (
    blocks_to_markdown,
    extract_doc_ids_from_column_value,
    markdown_to_blocks,
)


class TestExtractDocIds:
    def test_returns_object_id(self) -> None:
        raw = '{"files":[{"linkToFile":"https://x/docs/1","fileType":"MONDAY_DOC","docId":67890,"objectId":54321}]}'
        assert extract_doc_ids_from_column_value(raw) == [54321]

    def test_multiple_files(self) -> None:
        raw = '{"files":[{"objectId":1,"fileType":"MONDAY_DOC"},{"objectId":2,"fileType":"MONDAY_DOC"}]}'
        assert extract_doc_ids_from_column_value(raw) == [1, 2]

    def test_ignores_non_monday_doc_files(self) -> None:
        """If a doc column happens to also hold a non-doc file, skip it."""
        raw = (
            '{"files":[{"objectId":10,"fileType":"MONDAY_DOC"},{"objectId":20,"fileType":"ASSET"}]}'
        )
        assert extract_doc_ids_from_column_value(raw) == [10]

    def test_falls_back_to_doc_id_when_object_id_missing(self) -> None:
        raw = '{"files":[{"docId":777,"fileType":"MONDAY_DOC"}]}'
        assert extract_doc_ids_from_column_value(raw) == [777]

    def test_empty_returns_empty(self) -> None:
        assert extract_doc_ids_from_column_value("") == []
        assert extract_doc_ids_from_column_value(None) == []
        assert extract_doc_ids_from_column_value('{"files":[]}') == []

    def test_malformed_returns_empty(self) -> None:
        assert extract_doc_ids_from_column_value("not json") == []


class TestMarkdownToBlocks:
    def test_plain_paragraph(self) -> None:
        blocks = markdown_to_blocks("Hello world")
        assert len(blocks) == 1
        assert blocks[0]["type"] == "normal_text"
        assert "Hello world" in str(blocks[0]["content"])

    def test_h1_is_large_title(self) -> None:
        blocks = markdown_to_blocks("# Title")
        assert blocks[0]["type"] == "large_title"
        assert "Title" in str(blocks[0]["content"])

    def test_h2_is_medium_title(self) -> None:
        assert markdown_to_blocks("## Sub")[0]["type"] == "medium_title"

    def test_h3_is_small_title(self) -> None:
        assert markdown_to_blocks("### Small")[0]["type"] == "small_title"

    def test_bullet_list(self) -> None:
        md = "- one\n- two\n- three"
        blocks = markdown_to_blocks(md)
        assert len(blocks) == 3
        assert all(b["type"] == "bulleted_list" for b in blocks)

    def test_numbered_list(self) -> None:
        blocks = markdown_to_blocks("1. one\n2. two")
        assert [b["type"] for b in blocks] == ["numbered_list", "numbered_list"]

    def test_task_list_unchecked(self) -> None:
        blocks = markdown_to_blocks("- [ ] todo")
        assert blocks[0]["type"] == "check_list"
        # unchecked items omit the `checked` key (matches monday's wire shape)
        assert "checked" not in blocks[0]["content"]

    def test_task_list_checked(self) -> None:
        blocks = markdown_to_blocks("- [x] done")
        assert blocks[0]["type"] == "check_list"
        assert blocks[0]["content"]["checked"] is True

    def test_task_list_capital_x_also_checked(self) -> None:
        blocks = markdown_to_blocks("- [X] done")
        assert blocks[0]["content"]["checked"] is True

    def test_task_list_does_not_consume_plain_bullet(self) -> None:
        """`- foo` (no `[ ]`) must remain a bulleted_list, not a check_list."""
        blocks = markdown_to_blocks("- plain")
        assert blocks[0]["type"] == "bulleted_list"

    def test_blockquote(self) -> None:
        blocks = markdown_to_blocks("> wise words")
        assert blocks[0]["type"] == "quote"

    def test_divider(self) -> None:
        blocks = markdown_to_blocks("---")
        assert blocks[0]["type"] == "divider"

    def test_code_fence(self) -> None:
        md = "```python\nprint('hi')\n```"
        blocks = markdown_to_blocks(md)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code"

    def test_multi_block(self) -> None:
        md = "# Heading\n\nParagraph text.\n\n- bullet 1\n- bullet 2"
        blocks = markdown_to_blocks(md)
        types = [b["type"] for b in blocks]
        assert types == ["large_title", "normal_text", "bulleted_list", "bulleted_list"]

    def test_empty_returns_empty(self) -> None:
        assert markdown_to_blocks("") == []
        assert markdown_to_blocks("   \n  \n  ") == []


class TestBlocksToMarkdown:
    def _block(self, t: str, text: str = "") -> dict:
        return {
            "type": t,
            "content": {"deltaFormat": [{"insert": text}]} if text else {},
        }

    def test_single_paragraph(self) -> None:
        md = blocks_to_markdown([self._block("normal_text", "Hello")])
        assert "Hello" in md

    def test_heading_levels(self) -> None:
        out = blocks_to_markdown(
            [
                self._block("large_title", "H1"),
                self._block("medium_title", "H2"),
                self._block("small_title", "H3"),
            ]
        )
        assert "# H1" in out
        assert "## H2" in out
        assert "### H3" in out

    def test_heading_legacy_names_still_render(self) -> None:
        """Back-compat: older monday docs may still carry the renamed types
        (`heading`, `sub_heading`, `small_heading`, `bullet_list`) — reads
        normalize them via _READ_ALIASES so existing content stays renderable."""
        out = blocks_to_markdown(
            [
                self._block("heading", "H1"),
                self._block("sub_heading", "H2"),
                self._block("small_heading", "H3"),
                self._block("bullet_list", "legacy"),
            ]
        )
        assert "# H1" in out
        assert "## H2" in out
        assert "### H3" in out
        assert "- legacy" in out

    def test_bullet_list(self) -> None:
        out = blocks_to_markdown(
            [
                self._block("bulleted_list", "a"),
                self._block("bulleted_list", "b"),
            ]
        )
        assert "- a" in out
        assert "- b" in out

    def test_numbered_list(self) -> None:
        out = blocks_to_markdown(
            [
                self._block("numbered_list", "a"),
                self._block("numbered_list", "b"),
            ]
        )
        assert "1. a" in out
        assert "2. b" in out

    def test_check_list_unchecked(self) -> None:
        out = blocks_to_markdown([self._block("check_list", "todo")])
        assert "- [ ] todo" in out

    def test_check_list_checked(self) -> None:
        # `checked: true` inside content (mirroring monday's live shape).
        block = {
            "type": "check_list",
            "content": {"deltaFormat": [{"insert": "done"}], "checked": True},
        }
        out = blocks_to_markdown([block])
        assert "- [x] done" in out

    def test_check_list_with_space_in_type_name(self) -> None:
        """Live API returns `"check list"` with a space; _normalize_type
        must funnel it to the `check_list` branch, not the plain-text fallback."""
        block = {
            "type": "check list",
            "content": '{"deltaFormat":[{"insert":"unchecked"}]}',
        }
        out = blocks_to_markdown([block])
        assert "- [ ] unchecked" in out

    def test_check_list_roundtrip(self) -> None:
        """Markdown task list → blocks → markdown must preserve the marks."""
        md_in = "- [ ] todo\n- [x] done\n"
        blocks = markdown_to_blocks(md_in)
        out = blocks_to_markdown(blocks)
        assert "- [ ] todo" in out
        assert "- [x] done" in out

    def test_quote(self) -> None:
        out = blocks_to_markdown([self._block("quote", "wise")])
        assert "> wise" in out

    def test_divider(self) -> None:
        out = blocks_to_markdown([{"type": "divider", "content": {}}])
        assert "---" in out

    def test_unknown_type_falls_back_to_plain_text(self) -> None:
        out = blocks_to_markdown([self._block("some_new_block", "content")])
        assert "content" in out

    def test_empty_block_list(self) -> None:
        assert blocks_to_markdown([]) == ""


class TestBlocksToMarkdownContainers:
    """Container blocks (notice/callout/layout/table) and parent_block_id.

    Regression for issue #1 — children with `parent_block_id` were silently
    detached from their container and rendered out-of-context (or, for some
    types, dropped entirely). Renderer now walks the parent→children tree.
    """

    @staticmethod
    def _block(
        bid: str, btype: str, text: str = "", parent: str | None = None
    ) -> dict:
        return {
            "id": bid,
            "type": btype,
            "content": {"deltaFormat": [{"insert": text}]} if text else {},
            "parent_block_id": parent,
        }

    def test_notice_renders_as_gfm_callout(self) -> None:
        out = blocks_to_markdown(
            [
                self._block("n1", "notice"),
                self._block("c1", "normal_text", "first inside", parent="n1"),
                self._block("c2", "normal_text", "second inside", parent="n1"),
            ]
        )
        assert "> [!NOTE]" in out
        assert "> first inside" in out
        assert "> second inside" in out

    def test_callout_renders_as_gfm_callout(self) -> None:
        out = blocks_to_markdown(
            [
                self._block("c", "callout"),
                self._block("k", "normal_text", "inside callout", parent="c"),
            ]
        )
        assert "> [!NOTE]" in out
        assert "> inside callout" in out

    def test_orphan_child_falls_back_to_top_level(self) -> None:
        """A child whose parent_block_id points to a non-existent id must
        still render (no silent drop)."""
        out = blocks_to_markdown(
            [
                self._block("a", "normal_text", "alpha"),
                self._block("orphan", "normal_text", "ghost", parent="missing"),
            ]
        )
        assert "alpha" in out
        assert "ghost" in out
        # Orphan should NOT be wrapped in a container marker — it has no parent.
        assert "> ghost" not in out

    def test_layout_container_renders_children_inline(self) -> None:
        """Layout is purely structural — its children render with no
        callout marker, just at top level."""
        out = blocks_to_markdown(
            [
                self._block("l", "layout"),
                self._block("c1", "normal_text", "left text", parent="l"),
                self._block("c2", "normal_text", "right text", parent="l"),
            ]
        )
        assert "left text" in out
        assert "right text" in out
        assert "[!LAYOUT]" not in out
        assert "[!NOTE]" not in out

    def test_table_container_preserves_cell_text(self) -> None:
        """Until proper table reconstruction lands, table cells must at
        least survive inside a `> [!TABLE]` blockquote — no silent drop."""
        out = blocks_to_markdown(
            [
                self._block("t", "table"),
                self._block("r1", "normal_text", "cell one", parent="t"),
                self._block("r2", "normal_text", "cell two", parent="t"),
            ]
        )
        assert "> [!TABLE]" in out
        assert "> cell one" in out
        assert "> cell two" in out

    def test_nested_notice_inside_notice(self) -> None:
        """Blockquote prefix must stack for nested containers."""
        out = blocks_to_markdown(
            [
                self._block("outer", "notice"),
                self._block("inner", "notice", parent="outer"),
                self._block(
                    "leaf", "normal_text", "deep inside", parent="inner"
                ),
            ]
        )
        # Inner notice's marker is rendered with the outer's prefix → `> > [!NOTE]`
        assert "> > [!NOTE]" in out
        assert "> > deep inside" in out

    def test_unknown_container_with_children_uses_generic_marker(self) -> None:
        """Future monday container types must degrade gracefully — emit a
        generic `[!TYPE]` marker rather than dropping children."""
        out = blocks_to_markdown(
            [
                self._block("x", "future_thing"),
                self._block("c", "normal_text", "rescued", parent="x"),
            ]
        )
        assert "rescued" in out
        # Generic marker uppercases the type.
        assert "[!FUTURE_THING]" in out

    def test_numbered_list_counter_isolated_per_container(self) -> None:
        """A numbered list inside a notice must not bleed counters with a
        numbered list outside it."""
        out = blocks_to_markdown(
            [
                self._block("o1", "numbered_list", "outer-a"),
                self._block("o2", "numbered_list", "outer-b"),
                self._block("n", "notice"),
                self._block("i1", "numbered_list", "inner-a", parent="n"),
                self._block("i2", "numbered_list", "inner-b", parent="n"),
            ]
        )
        assert "1. outer-a" in out
        assert "2. outer-b" in out
        # Inner list restarts at 1, blockquoted.
        assert "> 1. inner-a" in out
        assert "> 2. inner-b" in out

    def test_blocks_without_parent_block_id_render_unchanged(self) -> None:
        """Sanity: a flat list with no parent_block_id behaves exactly as
        before (covers the common path so tree-aware refactor doesn't
        regress non-container docs)."""
        flat = [
            {"type": "large_title", "content": {"deltaFormat": [{"insert": "T"}]}},
            {"type": "normal_text", "content": {"deltaFormat": [{"insert": "para"}]}},
            {"type": "bulleted_list", "content": {"deltaFormat": [{"insert": "x"}]}},
        ]
        out = blocks_to_markdown(flat)
        assert "# T" in out
        assert "para" in out
        assert "- x" in out

    def test_self_referencing_parent_treated_as_root(self) -> None:
        """Defensive: a block whose parent_block_id == its own id must not
        recurse infinitely. It renders as a normal root."""
        out = blocks_to_markdown(
            [self._block("s", "normal_text", "self-loop", parent="s")]
        )
        assert "self-loop" in out

    def test_empty_notice_still_emits_marker(self) -> None:
        """A notice with no children still preserves the 'this was a
        notice' context (otherwise it would silently disappear)."""
        out = blocks_to_markdown([self._block("n", "notice")])
        assert "[!NOTE]" in out


class TestBlocksToMarkdownTables:
    """monday's `table` block stores layout in `content.cells` as a
    row-major matrix of `{blockId}` references; each referenced cell
    has its visible text in a `normal_text` child. The renderer walks
    that matrix and emits a real markdown pipe table."""

    @staticmethod
    def _table_payload(cell_ids: list[list[str]]) -> dict:
        """Construct a table block's content.cells matrix as monday returns it
        (note: monday returns content as a JSON STRING; both shapes must work)."""
        return {
            "cells": [[{"blockId": cid} for cid in row] for row in cell_ids],
            "row_count": len(cell_ids),
            "column_count": len(cell_ids[0]) if cell_ids else 0,
        }

    @staticmethod
    def _cell(cell_id: str, table_id: str) -> dict:
        return {
            "id": cell_id,
            "type": "cell",
            "content": {},
            "parent_block_id": table_id,
        }

    @staticmethod
    def _cell_text(text_id: str, cell_id: str, text: str) -> dict:
        return {
            "id": text_id,
            "type": "normal_text",
            "content": {"deltaFormat": [{"insert": text}]},
            "parent_block_id": cell_id,
        }

    def _build_table(
        self, table_id: str, grid_text: list[list[str]]
    ) -> list[dict]:
        rows = len(grid_text)
        cols = len(grid_text[0]) if rows else 0
        cell_ids = [
            [f"{table_id}-c{r}-{c}" for c in range(cols)] for r in range(rows)
        ]
        blocks: list[dict] = [
            {
                "id": table_id,
                "type": "table",
                "content": self._table_payload(cell_ids),
                "parent_block_id": None,
            }
        ]
        for r, row in enumerate(grid_text):
            for c, txt in enumerate(row):
                cid = cell_ids[r][c]
                blocks.append(self._cell(cid, table_id))
                if txt:
                    blocks.append(self._cell_text(f"{cid}-t", cid, txt))
        return blocks

    def test_simple_2x2_table_renders_as_pipe_table(self) -> None:
        blocks = self._build_table(
            "t", [["Name", "Score"], ["Alice", "95"]]
        )
        out = blocks_to_markdown(blocks)
        # Header row.
        assert "| Name | Score |" in out
        # Separator row.
        assert "| --- | --- |" in out
        # Body row.
        assert "| Alice | 95 |" in out

    def test_4x3_table_preserves_row_and_column_order(self) -> None:
        blocks = self._build_table(
            "t",
            [
                ["A", "B", "C"],
                ["1", "2", "3"],
                ["x", "y", "z"],
                ["foo", "bar", "baz"],
            ],
        )
        out = blocks_to_markdown(blocks)
        assert "| A | B | C |" in out
        assert "| --- | --- | --- |" in out
        assert "| 1 | 2 | 3 |" in out
        assert "| x | y | z |" in out
        assert "| foo | bar | baz |" in out

    def test_empty_cell_renders_as_blank(self) -> None:
        blocks = self._build_table("t", [["a", "b"], ["c", ""]])
        out = blocks_to_markdown(blocks)
        # Empty cell becomes a blank between pipes (with the surrounding spaces).
        assert "| c |  |" in out

    def test_pipe_in_cell_text_is_escaped(self) -> None:
        """A literal `|` in cell text would break the row syntax — escape it."""
        blocks = self._build_table("t", [["a|b", "c"], ["d", "e"]])
        out = blocks_to_markdown(blocks)
        # Pipe is escaped as `\|` so markdown renderers don't split the row.
        assert r"a\|b" in out

    def test_table_with_content_as_json_string(self) -> None:
        """Real monday API returns block.content as a JSON-encoded string,
        not a parsed object. The renderer must re-parse."""
        # Build the structure, then re-encode the table block's content as a string.
        blocks = self._build_table("t", [["A", "B"], ["1", "2"]])
        import json as _json
        for b in blocks:
            if b["type"] == "table":
                b["content"] = _json.dumps(b["content"])
                break
        out = blocks_to_markdown(blocks)
        assert "| A | B |" in out
        assert "| 1 | 2 |" in out

    def test_malformed_table_falls_back_to_blockquote(self) -> None:
        """A `table` block with no/bad `cells` matrix falls back to the
        generic `[!TABLE]` blockquote so cell text isn't silently dropped."""
        blocks = [
            {
                "id": "t",
                "type": "table",
                "content": {},  # no cells matrix
                "parent_block_id": None,
            },
            {
                "id": "c1",
                "type": "normal_text",
                "content": {"deltaFormat": [{"insert": "rescue me"}]},
                "parent_block_id": "t",
            },
        ]
        out = blocks_to_markdown(blocks)
        assert "[!TABLE]" in out
        assert "rescue me" in out

    def test_table_inside_notice_renders_with_blockquote_prefix(self) -> None:
        """A table nested under a notice should render as a markdown table,
        but every line must be blockquote-prefixed by the parent notice."""
        notice = {
            "id": "n",
            "type": "notice_box",
            "content": {},
            "parent_block_id": None,
        }
        # Table sits under the notice — patch parent_block_id.
        table_blocks = self._build_table("t", [["A", "B"], ["1", "2"]])
        table_blocks[0]["parent_block_id"] = "n"
        out = blocks_to_markdown([notice, *table_blocks])
        # Notice marker present.
        assert "> [!NOTE]" in out
        # Table rows are prefixed with `> ` because they're inside the notice.
        assert "> | A | B |" in out
        assert "> | 1 | 2 |" in out


class TestRealMondayShapes:
    """Monday's actual responses contain quirks not documented upfront.

    Observed from live API reads:
    - Block types come back with spaces: "normal text" (not "normal_text").
    - content is a JSON string, not a parsed object.
    """

    def test_handles_type_with_space(self) -> None:
        block = {"type": "normal text", "content": '{"deltaFormat":[{"insert":"Hi"}]}'}
        assert "Hi" in blocks_to_markdown([block])

    def test_handles_json_string_content(self) -> None:
        # Delta content arrives as a string that must be re-parsed.
        block = {"type": "large_title", "content": '{"deltaFormat":[{"insert":"Big"}]}'}
        assert "# Big" in blocks_to_markdown([block])

    def test_empty_delta_renders_empty(self) -> None:
        """Empty doc: `{"deltaFormat":[]}` — blocks_to_markdown shouldn't crash."""
        block = {"type": "normal text", "content": '{"deltaFormat":[]}'}
        out = blocks_to_markdown([block])
        # No content, but also no crash
        assert isinstance(out, str)


class TestRoundTrip:
    """Markdown → blocks → markdown should preserve structure (not whitespace)."""

    @pytest.mark.parametrize(
        "md",
        [
            "# Heading\n\nParagraph.",
            "- one\n- two",
            "1. first\n2. second",
            "> quoted",
            "---",
        ],
    )
    def test_roundtrip_preserves_types(self, md: str) -> None:
        blocks = markdown_to_blocks(md)
        back = blocks_to_markdown(blocks)
        # Exact whitespace isn't guaranteed, but types and key text must survive.
        for line in md.splitlines():
            if line.strip():
                content = line.lstrip("# -1234567890.>").strip()
                if content and content != "---":
                    assert content in back
