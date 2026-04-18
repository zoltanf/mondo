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
        raw = '{"files":[{"objectId":10,"fileType":"MONDAY_DOC"},{"objectId":20,"fileType":"ASSET"}]}'
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

    def test_h1_is_heading(self) -> None:
        blocks = markdown_to_blocks("# Title")
        assert blocks[0]["type"] == "heading"
        assert "Title" in str(blocks[0]["content"])

    def test_h2_is_sub_heading(self) -> None:
        assert markdown_to_blocks("## Sub")[0]["type"] == "sub_heading"

    def test_h3_is_small_heading(self) -> None:
        assert markdown_to_blocks("### Small")[0]["type"] == "small_heading"

    def test_bullet_list(self) -> None:
        md = "- one\n- two\n- three"
        blocks = markdown_to_blocks(md)
        assert len(blocks) == 3
        assert all(b["type"] == "bullet_list" for b in blocks)

    def test_numbered_list(self) -> None:
        blocks = markdown_to_blocks("1. one\n2. two")
        assert [b["type"] for b in blocks] == ["numbered_list", "numbered_list"]

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
        assert types == ["heading", "normal_text", "bullet_list", "bullet_list"]

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
                self._block("heading", "H1"),
                self._block("sub_heading", "H2"),
                self._block("small_heading", "H3"),
            ]
        )
        assert "# H1" in out
        assert "## H2" in out
        assert "### H3" in out

    def test_bullet_list(self) -> None:
        out = blocks_to_markdown(
            [
                self._block("bullet_list", "a"),
                self._block("bullet_list", "b"),
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
        block = {"type": "heading", "content": '{"deltaFormat":[{"insert":"Big"}]}'}
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
