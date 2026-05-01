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
            blocks.append({"type": _BULLET_LIST_TYPE, "content": _text_content(m.group(1).strip())})
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


# Container blocks (notice_box/layout/table) hold their visible content in
# *child* blocks linked back via `parent_block_id`. The renderer walks that
# tree and emits GFM callout markers (`> [!NOTE]` etc.) so the structure
# round-trips and degrades to a plain blockquote in non-GFM renderers. See
# issue #1.
#
# Monday's `DocBlockContentType` enum spells the callout type `notice_box`;
# `notice` and `callout` are kept as read-side aliases in case older payloads
# or the issue reporter's terminology surfaces them.
# `layout` is a structural-only container — children render inline with no
# callout chrome, since plain markdown has no equivalent of multi-column.
_STRUCTURAL_MARKER = ""

_CONTAINER_MARKERS: dict[str, str] = {
    "notice_box": "[!NOTE]",
    "notice": "[!NOTE]",
    "callout": "[!NOTE]",
    "table": "[!TABLE]",
    "layout": _STRUCTURAL_MARKER,
}

_LEAF_TYPES = frozenset(
    {
        "divider",
        "large_title",
        "medium_title",
        "small_title",
        "bulleted_list",
        "numbered_list",
        "quote",
        "code",
        "normal_text",
    }
)


def _container_marker(btype: str, has_children: bool) -> str | None:
    """Resolve the container handling for a block.

    Returns:
        - a non-empty string ("[!NOTE]"): callout container — emit this marker
          and indent children with `"> "`.
        - `""` (empty string, `_STRUCTURAL_MARKER`): structural container
          (e.g. `layout`) — render children inline with no marker.
        - `None`: not a container at all; render as a leaf.

    Unknown types with children fall back to `[!{TYPE_UPPER}]` so we never
    silently drop content when monday adds a new container type.
    """
    if btype in _CONTAINER_MARKERS:
        return _CONTAINER_MARKERS[btype]
    if has_children and btype not in _LEAF_TYPES:
        return f"[!{btype.upper()}]" if btype else "[!CONTAINER]"
    return None


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Render a list of monday doc blocks as a markdown string.

    Walks the parent→children tree implied by `parent_block_id` so container
    blocks (notice/callout/layout/table) render with their inner content
    nested underneath, instead of children being detached and rendered out
    of context (issue #1).
    """
    if not blocks:
        return ""

    by_id: dict[str, dict[str, Any]] = {}
    for b in blocks:
        bid = b.get("id")
        if bid is not None:
            by_id[str(bid)] = b

    children_of: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    for b in blocks:
        bid = b.get("id")
        parent = b.get("parent_block_id")
        # Treat as root when: no parent set, parent missing from this list
        # (orphan — render at top so we don't silently drop), or self-cycle.
        if (
            parent is None
            or str(parent) == str(bid)
            or str(parent) not in by_id
        ):
            roots.append(b)
        else:
            children_of.setdefault(str(parent), []).append(b)

    lines: list[str] = []
    _render_block_list(roots, children_of, "", lines)
    return "\n".join(lines).rstrip() + "\n"


def _render_table(
    block: dict[str, Any],
    children_of: dict[str, list[dict[str, Any]]],
    prefix: str,
    lines: list[str],
) -> bool:
    """Render a `table` block as a markdown pipe table.

    monday's `table` block carries the layout in `content.cells` — a row-major
    matrix of `[{"blockId": ...}]` references. Each referenced block is a
    `cell` whose visible text lives in a `normal_text` child. The flat
    `parent_block_id` graph alone doesn't preserve column order, so we read
    the matrix to reconstruct the grid.

    Returns True when a real markdown table was emitted; False when the
    schema is missing/malformed and the caller should fall back to the
    generic `[!TABLE]` blockquote so cell text isn't silently dropped.
    """
    raw = block.get("content")
    if isinstance(raw, str):
        try:
            content = json.loads(raw)
        except ValueError:
            return False
    elif isinstance(raw, dict):
        content = raw
    else:
        return False

    cells_matrix = content.get("cells")
    if not isinstance(cells_matrix, list) or not cells_matrix:
        return False

    grid: list[list[str]] = []
    for row in cells_matrix:
        if not isinstance(row, list):
            return False
        row_texts: list[str] = []
        for cell_ref in row:
            cell_id = ""
            if isinstance(cell_ref, dict):
                ref = cell_ref.get("blockId")
                if ref is not None:
                    cell_id = str(ref)
            pieces: list[str] = []
            for child in children_of.get(cell_id, []):
                t = _extract_text(child.get("content"))
                if t:
                    pieces.append(t)
            cell_text = " ".join(pieces)
            # Escape pipes and collapse newlines so the row syntax stays valid.
            cell_text = cell_text.replace("|", r"\|").replace("\n", " ")
            row_texts.append(cell_text)
        grid.append(row_texts)

    if not grid or not grid[0]:
        return False

    col_count = max(len(row) for row in grid)
    grid = [row + [""] * (col_count - len(row)) for row in grid]

    # Header row + separator + body rows. The first matrix row is treated as
    # the header; markdown pipe tables require a separator after it.
    lines.append(f"{prefix}| " + " | ".join(grid[0]) + " |")
    lines.append(f"{prefix}| " + " | ".join(["---"] * col_count) + " |")
    for row in grid[1:]:
        lines.append(f"{prefix}| " + " | ".join(row) + " |")
    lines.append("")
    return True


def _render_block_list(
    siblings: list[dict[str, Any]],
    children_of: dict[str, list[dict[str, Any]]],
    prefix: str,
    lines: list[str],
) -> None:
    """Render a sibling group at indentation `prefix`.

    Numbered-list counter is local to this call — a `1. … 2. …` list inside
    a notice restarts at 1 independently of any list outside it.
    """
    numbered_counter = 0
    for block in siblings:
        btype = _normalize_type(block.get("type") or "")
        text = _extract_text(block.get("content"))
        bid = str(block.get("id") or "")
        kids = children_of.get(bid, [])

        if btype != "numbered_list":
            numbered_counter = 0

        if btype == "table" and _render_table(block, children_of, prefix, lines):
            continue

        marker = _container_marker(btype, has_children=bool(kids))
        if marker is not None:
            child_prefix = prefix + "> " if marker else prefix
            if marker:
                lines.append(f"{prefix}> {marker}")
            _render_block_list(kids, children_of, child_prefix, lines)
            lines.append("")
            continue

        # Leaf rendering.
        if btype == "divider":
            lines.append(f"{prefix}---")
        elif btype == "large_title":
            lines.append(f"{prefix}# {text}")
        elif btype == "medium_title":
            lines.append(f"{prefix}## {text}")
        elif btype == "small_title":
            lines.append(f"{prefix}### {text}")
        elif btype == "bulleted_list":
            lines.append(f"{prefix}- {text}")
        elif btype == "numbered_list":
            numbered_counter += 1
            lines.append(f"{prefix}{numbered_counter}. {text}")
        elif btype == "quote":
            lines.append(f"{prefix}> {text}")
        elif btype == "code":
            content = block.get("content") or {}
            lang = content.get("language", "") if isinstance(content, dict) else ""
            lines.append(f"{prefix}```{lang}")
            if text:
                lines.append(f"{prefix}{text}")
            lines.append(f"{prefix}```")
        elif text:
            # normal_text + any other leaf type we haven't taught.
            lines.append(f"{prefix}{text}")

        # Defensive: a leaf block with unexpected children would otherwise
        # drop them. Render at same prefix so content survives.
        if kids:
            _render_block_list(kids, children_of, prefix, lines)

        lines.append("")
