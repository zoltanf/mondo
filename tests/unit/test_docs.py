"""Tests for mondo.docs — doc column value parsing + markdown converters."""

from __future__ import annotations

import pytest

from mondo.docs import (
    blocks_to_html,
    blocks_to_markdown,
    blocks_to_mdx,
    coalesce_markdown_emphasis,
    collect_image_asset_ids,
    extract_doc_ids_from_column_value,
    markdown_to_blocks,
    normalize_markdown_tables,
    split_markdown_for_upload,
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

    @pytest.mark.parametrize(
        "marker,expected_checked",
        [
            (" ", False),  # unchecked
            ("x", True),  # checked, lowercase
            ("X", True),  # checked, capital
        ],
    )
    def test_task_list_marker(self, marker: str, expected_checked: bool) -> None:
        blocks = markdown_to_blocks(f"- [{marker}] todo")
        assert blocks[0]["type"] == "check_list"
        # Unchecked items omit the key entirely (mirrors monday's wire shape:
        # the API never sends `checked: false`).
        if expected_checked:
            assert blocks[0]["content"]["checked"] is True
        else:
            assert "checked" not in blocks[0]["content"]

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


class TestBlocksToMarkdownImages:
    def _image(self, asset_id: int | None, url: str = "") -> dict:
        content: dict = {"url": url}
        if asset_id is not None:
            content["assetId"] = asset_id
        return {"type": "image", "content": content}

    def test_image_without_map_emits_monday_url(self) -> None:
        """No download map → degrade to the (browser-only) monday url rather
        than silently dropping the image."""
        out = blocks_to_markdown([self._image(238776078, "https://x/img.png")])
        assert "![](https://x/img.png)" in out

    def test_image_with_map_uses_local_filename_and_alt(self) -> None:
        out = blocks_to_markdown(
            [self._image(238776078, "https://x/img.png")],
            images={"238776078": ("photo.png", "238776078-photo.png")},
        )
        assert "![photo.png](238776078-photo.png)" in out

    def test_image_with_unmapped_asset_keeps_url(self) -> None:
        out = blocks_to_markdown(
            [self._image(999, "https://x/img.png")],
            images={"238776078": ("photo.png", "238776078-photo.png")},
        )
        assert "![](https://x/img.png)" in out

    def test_image_normalizes_spaced_type(self) -> None:
        """monday returns the type as `"image"` already, but reads pass through
        `_normalize_type`; a spaced variant must still render."""
        block = {"type": "image", "content": {"assetId": 1, "url": "u"}}
        assert "![](u)" in blocks_to_markdown([block])

    def test_image_alt_escapes_closing_bracket(self) -> None:
        """An asset name containing `]` must not close the alt span early and
        corrupt the markdown."""
        out = blocks_to_markdown(
            [self._image(1, "https://x/img.png")],
            images={"1": ("a]b.png", "1-a-b.png")},
        )
        assert "![a\\]b.png](1-a-b.png)" in out

    def test_nested_image_inside_notice_renders(self) -> None:
        blocks = [
            {"id": "n", "type": "notice_box", "content": {}},
            {
                "id": "i",
                "type": "image",
                "parent_block_id": "n",
                "content": {"assetId": 7, "url": "https://x/n.png"},
            },
        ]
        out = blocks_to_markdown(blocks, images={"7": ("n.png", "7-n.png")})
        assert "> ![n.png](7-n.png)" in out


class TestCollectImageAssetIds:
    def test_collects_in_order_deduped(self) -> None:
        blocks = [
            {"type": "image", "content": {"assetId": 20}},
            {"type": "normal text", "content": {}},
            {"type": "image", "content": {"assetId": 10}},
            {"type": "image", "content": {"assetId": 20}},
        ]
        assert collect_image_asset_ids(blocks) == [20, 10]

    def test_accepts_string_asset_id(self) -> None:
        assert collect_image_asset_ids([{"type": "image", "content": '{"assetId":"55"}'}]) == [55]

    def test_skips_image_without_asset_id(self) -> None:
        assert collect_image_asset_ids([{"type": "image", "content": {"url": "u"}}]) == []

    def test_ignores_non_image_blocks(self) -> None:
        assert collect_image_asset_ids([{"type": "normal_text", "content": {"assetId": 1}}]) == []


class TestBlocksToMarkdownContainers:
    """Container blocks (notice/callout/layout/table) and parent_block_id.

    Regression for issue #1 — children with `parent_block_id` were silently
    detached from their container and rendered out-of-context (or, for some
    types, dropped entirely). Renderer now walks the parent→children tree.
    """

    @staticmethod
    def _block(bid: str, btype: str, text: str = "", parent: str | None = None) -> dict:
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
                self._block("leaf", "normal_text", "deep inside", parent="inner"),
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
        out = blocks_to_markdown([self._block("s", "normal_text", "self-loop", parent="s")])
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

    def _build_table(self, table_id: str, grid_text: list[list[str]]) -> list[dict]:
        rows = len(grid_text)
        cols = len(grid_text[0]) if rows else 0
        cell_ids = [[f"{table_id}-c{r}-{c}" for c in range(cols)] for r in range(rows)]
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

    def test_image_inside_cell_renders_with_local_filename(self) -> None:
        """Table cells can hold image children (not just text). They must
        render so downloaded images aren't orphaned (no markdown reference)."""
        blocks = [
            {
                "id": "t",
                "type": "table",
                "content": self._table_payload([["t-c0-0"]]),
                "parent_block_id": None,
            },
            self._cell("t-c0-0", "t"),
            {
                "id": "img",
                "type": "image",
                "content": {"assetId": 7, "url": "https://x/n.png"},
                "parent_block_id": "t-c0-0",
            },
        ]
        out = blocks_to_markdown(blocks, images={"7": ("n.png", "7-n.png")})
        assert "| ![n.png](7-n.png) |" in out

    def test_simple_2x2_table_renders_as_pipe_table(self) -> None:
        blocks = self._build_table("t", [["Name", "Score"], ["Alice", "95"]])
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


class TestSplitMarkdownForUpload:
    """Issue #59: auto-chunk large markdown on top-level block boundaries."""

    def test_small_input_single_chunk(self) -> None:
        assert split_markdown_for_upload("# Hi\n\nBody") == ["# Hi\n\nBody"]

    def test_empty_returns_empty(self) -> None:
        assert split_markdown_for_upload("   \n\n") == []

    def test_splits_on_blank_lines_under_limit(self) -> None:
        blocks = [f"Paragraph number {i} " + "x" * 50 for i in range(10)]
        md = "\n\n".join(blocks)
        chunks = split_markdown_for_upload(md, max_chars=200)
        assert len(chunks) > 1
        # Every chunk stays under the limit and round-trips to the original set.
        assert all(len(c) <= 200 for c in chunks)
        rejoined = "\n\n".join(chunks)
        for b in blocks:
            assert b in rejoined

    def test_never_splits_inside_code_fence(self) -> None:
        # A fenced block longer than the limit must stay a single chunk.
        code = "```\n" + "\n".join(f"line {i}" for i in range(40)) + "\n```"
        md = f"# Title\n\n{code}\n\nAfter"
        chunks = split_markdown_for_upload(md, max_chars=80)
        # Exactly one chunk contains the fence, fully intact.
        fence_chunks = [c for c in chunks if "```" in c]
        assert len(fence_chunks) == 1
        assert fence_chunks[0].count("```") == 2
        assert "line 0" in fence_chunks[0] and "line 39" in fence_chunks[0]

    def test_never_splits_inside_table(self) -> None:
        rows = "\n".join(f"| a{i} | b{i} |" for i in range(30))
        table = "| H1 | H2 |\n| --- | --- |\n" + rows
        md = f"Intro\n\n{table}\n\nOutro"
        chunks = split_markdown_for_upload(md, max_chars=120)
        table_chunks = [c for c in chunks if "| H1 | H2 |" in c]
        assert len(table_chunks) == 1
        # The whole table (header + separator + every body row) is one unit.
        assert "| a0 | b0 |" in table_chunks[0]
        assert "| a29 | b29 |" in table_chunks[0]

    def test_oversized_atomic_block_is_own_chunk(self) -> None:
        big = "word " * 4000  # one paragraph well over the limit
        chunks = split_markdown_for_upload(big, max_chars=1000)
        assert len(chunks) == 1
        assert chunks[0].strip() == big.strip()


class TestNormalizeMarkdownTables:
    """Issue #61: normalize ragged GFM table rows to the header column count."""

    def test_overflow_row_merges_into_last_column(self) -> None:
        md = (
            "| Date | iOS | Android | Web | Backend | DB | Notes |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| 2024-01 | 1 | 2 | 3 | 4 | 5 | release | <- iOS 4407 released |\n"
        )
        out = normalize_markdown_tables(md)
        body = out.splitlines()[2]
        cells = [c.strip() for c in body.strip().strip("|").split("|")]
        assert len(cells) == 7
        # The 8th trailing cell is merged into the last (7th) column.
        assert cells[-1] == "release <- iOS 4407 released"

    def test_short_row_is_padded(self) -> None:
        md = "| A | B | C |\n| --- | --- | --- |\n| 1 | 2 |\n"
        out = normalize_markdown_tables(md)
        body = out.splitlines()[2]
        cells = [c.strip() for c in body.strip().strip("|").split("|")]
        assert cells == ["1", "2", ""]

    def test_code_fence_pipes_untouched(self) -> None:
        md = "```\n| a | b | c | d |\n```\n"
        assert normalize_markdown_tables(md) == md

    def test_non_table_text_unchanged(self) -> None:
        md = "# Title\n\nA paragraph with a | pipe but no table.\n"
        assert normalize_markdown_tables(md) == md

    def test_inline_code_pipe_in_cell_not_split(self) -> None:
        # A `|` inside an inline-code span is cell content, not a separator, so
        # a well-formed row keeps its column count instead of being mangled.
        md = "| Cmd | Note |\n| --- | --- |\n| `a | b` | ok |\n"
        out = normalize_markdown_tables(md)
        assert out.splitlines()[2] == "| `a | b` | ok |"

    def test_escaped_pipe_in_cell_not_split(self) -> None:
        md = "| A | B |\n| --- | --- |\n| x \\| y | z |\n"
        out = normalize_markdown_tables(md)
        assert out.splitlines()[2] == "| x \\| y | z |"

    def test_multi_backtick_inline_code_pipe_not_split(self) -> None:
        # A double-backtick code span closes only on another double backtick,
        # so a `|` inside it is cell content, not a separator.
        md = "| Cmd | Note |\n| --- | --- |\n| ``a | b`` | ok |\n"
        out = normalize_markdown_tables(md)
        assert out.splitlines()[2] == "| ``a | b`` | ok |"

    def test_indented_code_block_not_treated_as_table(self) -> None:
        # A 4-space indented code block whose lines look like a ragged table
        # is code, not a GFM table — it must be left byte-for-byte unchanged.
        md = "    | A | B |\n    | --- | --- |\n    | 1 |\n"
        assert normalize_markdown_tables(md) == md

    def test_indented_separator_not_treated_as_table(self) -> None:
        # Header is unindented but the separator is indented 4 spaces (code),
        # so this is not a GFM table and following pipe text must be left as-is.
        md = "| A | B |\n    | --- | --- |\n| 1 |\n"
        assert normalize_markdown_tables(md) == md


class TestCoalesceMarkdownEmphasis:
    """Issue #62: rejoin fragmented bold runs from the server exporter."""

    def test_fragmented_bold_collapses_to_single_span(self) -> None:
        fragmented = (
            "**Caching is not a clear win here, ****an****d ****it**** ****i****s "
            "****not what resolved the incident**"
        )
        assert coalesce_markdown_emphasis(fragmented) == (
            "**Caching is not a clear win here, and it is not what resolved the incident**"
        )

    def test_bold_italic_triple_span_left_intact(self) -> None:
        assert coalesce_markdown_emphasis("***x***") == "***x***"

    def test_code_span_pipes_not_corrupted(self) -> None:
        md = "before `a****b` after"
        assert coalesce_markdown_emphasis(md) == md

    def test_multi_backtick_code_span_not_corrupted(self) -> None:
        # A literal `****` inside a double-backtick code span is real content,
        # not an export seam — leave it untouched.
        md = "before ``a****b`` after"
        assert coalesce_markdown_emphasis(md) == md

    def test_no_op_without_fragmentation(self) -> None:
        md = "**bold** and *italic* text"
        assert coalesce_markdown_emphasis(md) == md

    def test_standalone_thematic_break_preserved(self) -> None:
        # A lone `****` line is a horizontal rule, not a bold seam — keep it,
        # while still collapsing a real seam elsewhere in the same document.
        md = "**a ****b**\n\n****\n\nmore"
        assert coalesce_markdown_emphasis(md) == "**a b**\n\n****\n\nmore"


def _b(bid, btype, text="", parent=None):
    """Block fixture: text becomes deltaFormat content; empty → {}."""
    return {
        "id": bid,
        "type": btype,
        "content": {"deltaFormat": [{"insert": text}]} if text else {},
        "parent_block_id": parent,
    }


class TestBlocksToMdx:
    def test_markdown_passthrough_when_no_special_chars(self) -> None:
        blocks = [_b("h", "large_title", "Title"), _b("p", "normal_text", "plain prose")]
        assert blocks_to_mdx(blocks) == blocks_to_markdown(blocks)

    def test_escapes_angle_bracket_in_prose(self) -> None:
        out = blocks_to_mdx([_b("p", "normal_text", "use <Component> here")])
        assert r"use \<Component> here" in out

    def test_escapes_brace_in_prose(self) -> None:
        out = blocks_to_mdx([_b("p", "normal_text", "value {x}")])
        assert r"value \{x}" in out

    def test_does_not_escape_inside_code_block(self) -> None:
        """MDX never parses inside fenced code — escaping there would corrupt it."""
        block = {
            "id": "c",
            "type": "code",
            "content": {"deltaFormat": [{"insert": "<div>{x}</div>"}]},
        }
        out = blocks_to_mdx([block])
        assert "<div>{x}</div>" in out
        assert r"\<div>" not in out

    def test_callouts_stay_gfm_blockquotes(self) -> None:
        out = blocks_to_mdx([_b("n", "notice_box"), _b("c", "normal_text", "inside", parent="n")])
        assert "> [!NOTE]" in out

    def test_escapes_table_cell_text(self) -> None:
        blocks = [
            {"id": "t", "type": "table", "content": {"cells": [[{"blockId": "cell"}]]}},
            _b("cell", "table_cell", parent="t"),
            _b("txt", "normal_text", "a <b> c", parent="cell"),
        ]
        out = blocks_to_mdx(blocks)
        assert r"a \<b> c" in out

    def test_neutralizes_leading_import_keyword(self) -> None:
        # A prose line opening with `import` would be parsed as MDX ESM; the
        # leading letter is encoded so it renders as text instead.
        out = blocks_to_mdx([_b("p", "normal_text", "import the data first")])
        assert "&#105;mport the data first" in out  # 105 == ord('i')
        assert not out.strip().startswith("import")

    def test_neutralizes_leading_export_keyword(self) -> None:
        out = blocks_to_mdx([_b("p", "normal_text", "export your results")])
        assert "&#101;xport your results" in out  # 101 == ord('e')

    def test_import_mid_sentence_left_intact(self) -> None:
        out = blocks_to_mdx([_b("p", "normal_text", "we import the data")])
        assert "we import the data" in out

    def test_leading_import_inside_code_fence_left_intact(self) -> None:
        block = {
            "id": "c",
            "type": "code",
            "content": {"deltaFormat": [{"insert": "import os"}]},
        }
        out = blocks_to_mdx([block])
        assert "import os" in out
        assert "&#105;mport" not in out

    def test_leading_import_inside_unusual_lang_fence_left_intact(self) -> None:
        # A fence whose info string isn't plain `[\w-]*` (e.g. `c++`/`c#`) must
        # still be recognized so code content isn't rewritten as prose.
        block = {
            "id": "c",
            "type": "code",
            "content": {"deltaFormat": [{"insert": "import std"}], "language": "c++"},
        }
        out = blocks_to_mdx([block])
        assert "import std" in out
        assert "&#105;mport" not in out

    def test_tilde_line_inside_backtick_fence_does_not_desync(self) -> None:
        # A ``` block whose content has a ~~~ line must NOT be treated as a
        # fence close, or `import` after it would be wrongly neutralized.
        block = {
            "id": "c",
            "type": "code",
            "content": {"deltaFormat": [{"insert": "~~~\nimport os"}]},
        }
        out = blocks_to_mdx([block])
        assert "import os" in out
        assert "&#105;mport" not in out


class TestBlocksToHtml:
    def test_wraps_in_self_contained_document(self) -> None:
        out = blocks_to_html([_b("p", "normal_text", "hi")], title="My Doc")
        assert out.startswith("<!DOCTYPE html>")
        assert "<style>" in out
        assert "<title>My Doc</title>" in out
        assert '<h1 class="doc-title">My Doc</h1>' in out
        assert "<p>hi</p>" in out

    def test_carries_print_css_for_pdf(self) -> None:
        # PDF export (issue #68) hands this HTML to WeasyPrint, which renders
        # print media — so the stylesheet must define page geometry and force
        # light colors / page-break hints under @media print.
        out = blocks_to_html([_b("p", "normal_text", "hi")])
        assert "@page" in out
        assert "@media print" in out
        assert "break-inside" in out

    def test_headings(self) -> None:
        out = blocks_to_html(
            [
                _b("a", "large_title", "H1"),
                _b("b", "medium_title", "H2"),
                _b("c", "small_title", "H3"),
            ]
        )
        assert "<h1>H1</h1>" in out
        assert "<h2>H2</h2>" in out
        assert "<h3>H3</h3>" in out

    def test_escapes_html_in_text(self) -> None:
        out = blocks_to_html([_b("p", "normal_text", "a <b> & c")])
        assert "<p>a &lt;b&gt; &amp; c</p>" in out

    def test_bulleted_list_groups_into_ul(self) -> None:
        out = blocks_to_html([_b("1", "bulleted_list", "a"), _b("2", "bulleted_list", "b")])
        assert "<ul>" in out and "</ul>" in out
        assert out.count("<li>") == 2

    def test_numbered_list_groups_into_ol(self) -> None:
        out = blocks_to_html([_b("1", "numbered_list", "a"), _b("2", "numbered_list", "b")])
        assert "<ol>" in out and "</ol>" in out

    def test_checklist_renders_box_glyph(self) -> None:
        # Box glyphs, not `<input type=checkbox>` — the form control renders as
        # its own block in WeasyPrint (PDF), breaking the label onto a new line.
        checked = {
            "id": "1",
            "type": "check_list",
            "content": {"deltaFormat": [{"insert": "done"}], "checked": True},
        }
        unchecked = _b("2", "check_list", "todo")
        out = blocks_to_html([checked, unchecked])
        assert 'class="checklist"' in out
        assert "<input" not in out
        assert "<li>☑ done</li>" in out
        assert "<li>☐ todo</li>" in out

    def test_code_block(self) -> None:
        block = {
            "id": "c",
            "type": "code",
            "content": {"deltaFormat": [{"insert": "x = 1 < 2"}], "language": "python"},
        }
        out = blocks_to_html([block])
        assert '<pre><code class="language-python">x = 1 &lt; 2</code></pre>' in out

    def test_divider_and_quote(self) -> None:
        out = blocks_to_html([_b("d", "divider"), _b("q", "quote", "wise")])
        assert "<hr>" in out
        assert "<blockquote>wise</blockquote>" in out

    def test_notice_box_renders_as_aside(self) -> None:
        out = blocks_to_html([_b("n", "notice_box"), _b("c", "normal_text", "inside", parent="n")])
        assert '<aside class="notice">' in out
        assert "<p>inside</p>" in out

    def test_layout_renders_children_in_div(self) -> None:
        out = blocks_to_html([_b("l", "layout"), _b("c", "normal_text", "col", parent="l")])
        assert '<div class="layout">' in out
        assert "<p>col</p>" in out

    def test_image_without_map_keeps_url(self) -> None:
        block = {"id": "i", "type": "image", "content": {"assetId": 7, "url": "https://x/a.png"}}
        out = blocks_to_html([block])
        assert '<img src="https://x/a.png" alt="">' in out

    def test_image_with_map_embeds_data_uri(self) -> None:
        block = {"id": "i", "type": "image", "content": {"assetId": 7, "url": "https://x/a.png"}}
        out = blocks_to_html([block], images={"7": ("photo.png", "data:image/png;base64,AAA")})
        assert '<img src="data:image/png;base64,AAA" alt="photo.png">' in out

    def test_escapes_hostile_image_url(self) -> None:
        block = {
            "id": "i",
            "type": "image",
            "content": {"assetId": 7, "url": 'https://x/a.png"><script>alert(1)</script>'},
        }
        out = blocks_to_html([block])
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_escapes_hostile_image_alt(self) -> None:
        block = {"id": "i", "type": "image", "content": {"assetId": 7, "url": "https://x/a.png"}}
        out = blocks_to_html(
            [block], images={"7": ('"><script>x</script>', "data:image/png;base64,AAA")}
        )
        assert "<script>x</script>" not in out

    def test_escapes_hostile_title(self) -> None:
        out = blocks_to_html(
            [_b("p", "normal_text", "hi")], title="</title><script>alert(1)</script>"
        )
        assert "<script>alert(1)</script>" not in out
        assert "&lt;/title&gt;" in out

    def test_table_renders_html_table(self) -> None:
        # Matrix references *cell* blocks (parented to the table); each cell's
        # visible text lives in a child block parented to the cell.
        blocks = [
            {
                "id": "t",
                "type": "table",
                "content": {
                    "cells": [
                        [{"blockId": "h1"}, {"blockId": "h2"}],
                        [{"blockId": "c1"}, {"blockId": "c2"}],
                    ]
                },
            },
            _b("h1", "table_cell", parent="t"),
            _b("h2", "table_cell", parent="t"),
            _b("c1", "table_cell", parent="t"),
            _b("c2", "table_cell", parent="t"),
            _b("h1t", "normal_text", "A", parent="h1"),
            _b("h2t", "normal_text", "B", parent="h2"),
            _b("c1t", "normal_text", "1", parent="c1"),
            _b("c2t", "normal_text", "2", parent="c2"),
        ]
        out = blocks_to_html(blocks)
        assert "<table>" in out
        assert "<th>A</th>" in out and "<th>B</th>" in out
        assert "<td>1</td>" in out and "<td>2</td>" in out

    def test_empty_blocks(self) -> None:
        out = blocks_to_html([], title="Empty")
        assert out.startswith("<!DOCTYPE html>")
        assert "<title>Empty</title>" in out
