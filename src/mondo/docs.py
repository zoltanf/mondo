"""monday Doc column helpers: value parsing + markdown ↔ block conversion.

Scope (plan §6.4 / monday-api.md §11.5.22):
- `extract_doc_ids_from_column_value` reads the doc column's JSON value and
  returns the `objectId`(s) pointing to workspace doc(s).
- `markdown_to_blocks` converts a markdown source into a list of monday's
  `CreateBlockInput` dicts. Supported blocks: heading (h1/h2/h3),
  normal_text, bullet_list, numbered_list, quote, code, divider.
- `blocks_to_markdown` reverses the above for display.

Unsupported markdown (images, tables, nested lists, inline formatting)
round-trips through `normal_text` — we prefer correctness over feature parity.
"""

from __future__ import annotations

import json
import re
from typing import Any

# --- doc column value parser ------------------------------------------------


def extract_doc_ids_from_column_value(raw: str | None) -> list[int]:
    """Pull `objectId` (or fall back to `docId`) from a doc column's value JSON.

    Returns an empty list on missing / malformed input — callers should
    handle "no doc yet" gracefully.
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    files = parsed.get("files") if isinstance(parsed, dict) else None
    if not isinstance(files, list):
        return []
    ids: list[int] = []
    for entry in files:
        if not isinstance(entry, dict):
            continue
        # Only monday docs carry the pointer we want. Other file entries (assets)
        # sometimes live in the same column — skip them.
        if entry.get("fileType") not in (None, "MONDAY_DOC"):
            continue
        pointer = entry.get("objectId") if entry.get("objectId") is not None else entry.get("docId")
        if not isinstance(pointer, (int, str, float)):
            continue
        try:
            ids.append(int(pointer))
        except ValueError:
            continue
    return ids


# --- markdown → blocks ------------------------------------------------------

# Monday's `DocBlockContentType` enum (API 2026-01) — note that the old
# `heading`/`sub_heading`/`small_heading`/`bullet_list` names were renamed;
# we emit the current names but `blocks_to_markdown` accepts both for
# back-compat when reading older docs.
_HEADING_TYPES = {1: "large_title", 2: "medium_title", 3: "small_title"}
_BULLET_LIST_TYPE = "bulleted_list"

_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*)$")
_DIVIDER_RE = re.compile(r"^\s*(?:---+|\*\*\*+|___+)\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*```\s*([\w-]*)\s*$")


def _text_content(text: str) -> dict[str, Any]:
    """Monday's text-bearing blocks use a Quill-like delta format."""
    return {"deltaFormat": [{"insert": text}]}


def markdown_to_blocks(md: str) -> list[dict[str, Any]]:
    """Convert markdown to a list of monday `CreateBlockInput` dicts."""
    if not md or not md.strip():
        return []

    lines = md.splitlines()
    blocks: list[dict[str, Any]] = []
    i = 0
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines).strip()
            if text:
                blocks.append({"type": "normal_text", "content": _text_content(text)})
            paragraph_lines.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        # Fenced code block. Monday's create_doc_block rejects a `language`
        # key in content (2026-01: "bad request") — so we drop it on write.
        # The language hint is still recovered on read via blocks_to_markdown.
        fence = _CODE_FENCE_RE.match(line)
        if fence:
            flush_paragraph()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not _CODE_FENCE_RE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            content: dict[str, Any] = {"deltaFormat": [{"insert": "\n".join(code_lines)}]}
            blocks.append({"type": "code", "content": content})
            continue

        # Horizontal rule / divider
        if _DIVIDER_RE.match(line):
            flush_paragraph()
            blocks.append({"type": "divider", "content": {}})
            i += 1
            continue

        # Heading
        m = _HEADING_RE.match(line)
        if m:
            flush_paragraph()
            level = min(len(m.group(1)), 3)
            text = m.group(2).strip()
            blocks.append({"type": _HEADING_TYPES[level], "content": _text_content(text)})
            i += 1
            continue

        # Blockquote
        m = _QUOTE_RE.match(line)
        if m:
            flush_paragraph()
            blocks.append({"type": "quote", "content": _text_content(m.group(1).strip())})
            i += 1
            continue

        # Bullet list
        m = _BULLET_RE.match(line)
        if m:
            flush_paragraph()
            blocks.append(
                {"type": _BULLET_LIST_TYPE, "content": _text_content(m.group(1).strip())}
            )
            i += 1
            continue

        # Numbered list
        m = _NUMBERED_RE.match(line)
        if m:
            flush_paragraph()
            blocks.append({"type": "numbered_list", "content": _text_content(m.group(1).strip())})
            i += 1
            continue

        # Default: paragraph continuation
        paragraph_lines.append(stripped)
        i += 1

    flush_paragraph()
    return blocks


# --- blocks → markdown ------------------------------------------------------


def _extract_text(content: Any) -> str:
    """Pull the plain text out of a block's content field.

    monday's actual API returns `content` as a JSON-encoded **string** (not a
    parsed object); we detect and re-parse. Known shape:
    `{"deltaFormat": [{"insert": "..."}]}`.
    """
    if not content:
        return ""
    # monday returns content as a JSON string in many API versions — re-parse.
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except ValueError:
            return content  # plain string fallback
        content = parsed
    if not isinstance(content, dict):
        return str(content)

    delta = content.get("deltaFormat")
    if isinstance(delta, list):
        pieces = [d.get("insert", "") for d in delta if isinstance(d, dict)]
        return "".join(pieces)

    # Fall-through attempts — some monday variants just embed "text" directly.
    for key in ("text", "value", "plainText"):
        val = content.get(key)
        if isinstance(val, str):
            return val
    return ""


_READ_ALIASES = {
    # old name → normalized-for-dispatch name
    "heading": "large_title",
    "sub_heading": "medium_title",
    "small_heading": "small_title",
    "bullet_list": "bulleted_list",
}


def _normalize_type(btype: str) -> str:
    """Normalize a block type read from monday so dispatch works regardless
    of schema age. Strips spaces (monday sometimes returns "normal text"
    rather than "normal_text") and maps deprecated names to their current
    `DocBlockContentType` enum values."""
    normalized = btype.replace(" ", "_")
    return _READ_ALIASES.get(normalized, normalized)


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Render a list of monday doc blocks as a markdown string."""
    if not blocks:
        return ""
    lines: list[str] = []
    numbered_counter = 0

    for block in blocks:
        btype = _normalize_type(block.get("type") or "")
        text = _extract_text(block.get("content"))
        if btype != "numbered_list":
            numbered_counter = 0

        if btype == "divider":
            lines.append("---")
        elif btype == "large_title":
            lines.append(f"# {text}")
        elif btype == "medium_title":
            lines.append(f"## {text}")
        elif btype == "small_title":
            lines.append(f"### {text}")
        elif btype == "bulleted_list":
            lines.append(f"- {text}")
        elif btype == "numbered_list":
            numbered_counter += 1
            lines.append(f"{numbered_counter}. {text}")
        elif btype == "quote":
            lines.append(f"> {text}")
        elif btype == "code":
            content = block.get("content") or {}
            lang = content.get("language", "") if isinstance(content, dict) else ""
            lines.append(f"```{lang}")
            if text:
                lines.append(text)
            lines.append("```")
        else:
            # normal_text + any unknown type we haven't taught: fall back to text
            if text:
                lines.append(text)

        lines.append("")  # blank line between blocks for readability

    return "\n".join(lines).rstrip() + "\n"
