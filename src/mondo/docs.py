"""monday Doc column helpers: value parsing + markdown ↔ block conversion.

Scope (plan §6.4 / monday-api.md §11.5.22):
- `extract_doc_ids_from_column_value` reads the doc column's JSON value and
  returns the `objectId`(s) pointing to workspace doc(s).
- `markdown_to_blocks` converts a markdown source into a list of monday's
  `CreateBlockInput` dicts. Supported blocks: heading (h1/h2/h3),
  normal_text, bullet_list, numbered_list, check_list (GFM task list
  syntax `- [ ] / - [x]`), quote, code, divider.
- `blocks_to_markdown` reverses the above for display. `image` blocks render
  as `![alt](ref)`; pass an `images` map (assetId → (alt, local filename)) to
  rewrite the monday `url` to a downloaded local file — see
  `mondo.cli._doc_images`. Without the map they keep the (browser-only)
  monday `url`.

Unsupported markdown (nested lists, inline formatting) round-trips through
`normal_text` — we prefer correctness over feature parity.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
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


# --- markdown preprocessing / chunking --------------------------------------

_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")


def _split_table_row(line: str) -> list[str]:
    """Split a GFM table row into its cell texts.

    Strips one leading/trailing border pipe, then splits on each remaining
    cell-separator `|`. A `\\|` escape and any `|` inside an inline-code span
    stay inside their cell, so a cell like `` `a|b` `` is not mis-split. Code
    spans may use a run of N backticks, closed only by another run of N (GFM),
    so `` ``a|b`` `` is handled too — not just single-backtick spans.
    """
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    cells: list[str] = []
    buf: list[str] = []
    fence = 0  # length of the backtick run that opened the current span; 0 = outside code
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == "`":
            j = i
            while j < n and body[j] == "`":
                j += 1
            run = j - i
            if fence == 0:
                fence = run  # open a span
            elif run == fence:
                fence = 0  # a matching run closes it
            buf.append("`" * run)
            i = j
            continue
        if ch == "|" and fence == 0 and (i == 0 or body[i - 1] != "\\"):
            cells.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    cells.append("".join(buf))
    return [c.strip() for c in cells]


def _is_indented_code(line: str) -> bool:
    """True when `line` is a markdown indented code block (4+ leading spaces or
    a leading tab). Such a line is code, never a GFM table row — even if it
    happens to contain pipes."""
    return line[:1] == "\t" or (len(line) - len(line.lstrip(" "))) >= 4


def _is_table_header(lines: list[str], i: int) -> bool:
    """True when line `i` is a GFM table header: a non-blank `| … |` row
    immediately followed by a `|---|---|` separator row. Indented code blocks
    are excluded so a code sample containing pipes is never rewritten."""
    return (
        i + 1 < len(lines)
        and not _is_indented_code(lines[i])
        and not _is_indented_code(lines[i + 1])
        and "|" in lines[i]
        and bool(lines[i].strip())
        and _TABLE_SEPARATOR_RE.match(lines[i + 1]) is not None
        and "|" in lines[i + 1]
    )


def normalize_markdown_tables(md: str) -> str:
    """Normalize every GFM table body row to its header's column count.

    A runaway body row with MORE cells than the header otherwise spawns an
    extra column server-side (issue #61). Short rows are padded with empty
    cells; overflow rows have their extra trailing cells MERGED into the last
    column (joined with a space) so no data is lost. Pipe characters inside
    fenced code blocks are left untouched.
    """
    lines = md.splitlines()
    out: list[str] = []
    in_fence = False
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _CODE_FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if in_fence:
            out.append(line)
            i += 1
            continue
        # A table is a header row of `| ... |` immediately followed by a
        # `|---|---|` separator. Detect that pair, then normalize body rows.
        if _is_table_header(lines, i):
            col_count = len(_split_table_row(line))
            out.append(line)
            out.append(lines[i + 1])
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                cells = _split_table_row(lines[i])
                if len(cells) > col_count:
                    cells = [*cells[: col_count - 1], " ".join(cells[col_count - 1 :])]
                elif len(cells) < col_count:
                    cells = [*cells, *([""] * (col_count - len(cells)))]
                out.append("| " + " | ".join(cells) + " |")
                i += 1
            continue
        out.append(line)
        i += 1
    trailing_newline = "\n" if md.endswith("\n") else ""
    return "\n".join(out) + trailing_newline


def split_markdown_for_upload(md: str, *, max_chars: int = 8000) -> list[str]:
    """Split markdown into chunks each under `max_chars`, on blank-line
    (top-level block) boundaries only.

    Never splits inside a fenced code block (```...```) or in the middle of a
    contiguous GFM table (header + separator + body rows). A single atomic
    block larger than `max_chars` is emitted as its own chunk (it can't be
    split further without corrupting it).
    """
    if not md.strip():
        return []

    blocks = _atomic_blocks(md)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for block in blocks:
        block_len = len(block)
        # +2 accounts for the blank-line separator rejoining blocks.
        if current and current_len + block_len + 2 > max_chars:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(block)
        current_len += block_len + 2

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _atomic_blocks(md: str) -> list[str]:
    """Break markdown into atomic blocks at blank-line boundaries, keeping
    fenced code blocks and contiguous GFM tables intact as single units."""
    lines = md.splitlines()
    blocks: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(lines)

    def flush() -> None:
        if buf:
            text = "\n".join(buf).strip("\n")
            if text.strip():
                blocks.append(text)
            buf.clear()

    while i < n:
        line = lines[i]
        if _CODE_FENCE_RE.match(line):
            # An atomic fenced block starts a fresh block and absorbs every
            # line through the closing fence (never split inside).
            flush()
            fence_lines = [line]
            i += 1
            while i < n and not _CODE_FENCE_RE.match(lines[i]):
                fence_lines.append(lines[i])
                i += 1
            if i < n:
                fence_lines.append(lines[i])
                i += 1
            blocks.append("\n".join(fence_lines))
            continue
        if _is_table_header(lines, i):
            # A contiguous table (header + separator + body) is one atomic
            # block — never split across a chunk boundary.
            flush()
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                table_lines.append(lines[i])
                i += 1
            blocks.append("\n".join(table_lines))
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        buf.append(line)
        i += 1

    flush()
    return blocks


# --- markdown → blocks ------------------------------------------------------

# Monday's `DocBlockContentType` enum (API 2026-01) — note that the old
# `heading`/`sub_heading`/`small_heading`/`bullet_list` names were renamed;
# we emit the current names but `blocks_to_markdown` accepts both for
# back-compat when reading older docs.
_HEADING_TYPES = {1: "large_title", 2: "medium_title", 3: "small_title"}
_BULLET_LIST_TYPE = "bulleted_list"

_TASK_LIST_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*)$")
_DIVIDER_RE = re.compile(r"^\s*(?:---+|\*\*\*+|___+)\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*```\s*([\w-]*)\s*$")


def _text_content(text: str, *, checked: bool = False) -> dict[str, Any]:
    """Monday's text-bearing blocks use a Quill-like delta format.

    `checked=True` emits a `check_list`-style flag; unchecked items omit the
    key to mirror monday's wire shape (the live API never sends `checked: false`).
    """
    content: dict[str, Any] = {"deltaFormat": [{"insert": text}]}
    if checked:
        content["checked"] = True
    return content


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

        # GFM task list (must match before plain bullet list, since a
        # task-list line is a bullet line with `[x]`/`[ ]` after the marker).
        # monday models checked state via a `checked: true` flag in content;
        # unchecked items omit the key.
        m = _TASK_LIST_RE.match(line)
        if m:
            flush_paragraph()
            checked = m.group(1).lower() == "x"
            content = _text_content(m.group(2).strip(), checked=checked)
            blocks.append({"type": "check_list", "content": content})
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


# --- export markdown post-processing ----------------------------------------

# A fenced code block or an inline backtick span — content we must never touch
# when coalescing emphasis (a literal `****` there is real, not fragmentation).
# The inline alternative matches a run of N backticks closed by a matching run
# (via the \1 backreference), so multi-backtick spans like `` ``a****b`` `` are
# protected too, not just single-backtick ones.
_CODE_SPAN_OR_FENCE_RE = re.compile(r"```[\s\S]*?```|(`+)(?:(?!\1).)+?\1")

# Zero-width bold boundary: a bold-close immediately followed by a bold-open,
# i.e. a literal `****` that isn't part of a `***bold-italic***` triple span.
# Bracketed by non-`*` (or string edge) so `***` runs are left intact. The
# exporter scatters these seams next to spaces too (`here, ****an`, `it**** **
# **i`), so no non-space guard — instead `_collapse_bold_seams` skips whole
# lines that are thematic breaks (a lone `****`), the one false positive.
_FRAGMENTED_BOLD_RE = re.compile(r"(?<!\*)\*\*\*\*(?!\*)")

# A line that is *only* asterisks (3+) is a thematic break / horizontal rule,
# not a fragmented-bold seam — never strip its asterisks.
_THEMATIC_BREAK_RE = re.compile(r"^\s*\*{3,}\s*$")


def _collapse_bold_seams(text: str) -> str:
    """Strip `****` seams from `text`, but leave a standalone thematic-break
    line (a lone `****`) intact."""
    return "\n".join(
        line if _THEMATIC_BREAK_RE.match(line) else _FRAGMENTED_BOLD_RE.sub("", line)
        for line in text.split("\n")
    )


def coalesce_markdown_emphasis(md: str) -> str:
    """Merge fragmented bold runs in server-exported markdown (issue #62).

    `export_markdown_from_doc` returns contiguous bold text as many adjacent
    `**…**` spans, e.g. `**a ****b****c**`, leaving a zero-width `****` at each
    seam. Collapsing every `****` (a bold-close immediately followed by a
    bold-open) in a single pass rejoins them into one span: the regex
    guards each match with non-`*` boundaries, so a removal joins two
    non-`*` chars and can never manufacture a fresh seam.

    Content inside backtick code spans / fenced blocks is preserved verbatim,
    `***bold-italic***` triple-asterisk spans are left intact (the pattern only
    matches an isolated four-asterisk seam), and a standalone `****` line — a
    thematic break / horizontal rule — is never stripped.
    """
    if "****" not in md:
        return md

    segments: list[str] = []
    last = 0
    for m in _CODE_SPAN_OR_FENCE_RE.finditer(md):
        segments.append(_collapse_bold_seams(md[last : m.start()]))
        segments.append(m.group(0))  # code content: untouched
        last = m.end()
    segments.append(_collapse_bold_seams(md[last:]))
    return "".join(segments)


# --- blocks → markdown ------------------------------------------------------


def _as_content_dict(content: Any) -> dict[str, Any] | None:
    """Normalize a block's `content` field to a dict, or None if not parseable.

    monday's API returns `content` as a JSON-encoded string in some versions
    and as an already-parsed dict in others. Callers that need keyed access
    funnel through this helper instead of repeating the str-or-dict dance.
    """
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            return None
    return content if isinstance(content, dict) else None


def _extract_text(content: Any) -> str:
    """Pull the plain text out of a block's content field.

    Known shape: `{"deltaFormat": [{"insert": "..."}]}`. Falls back to
    `text`/`value`/`plainText` for monday variants that embed text directly,
    and to the raw string for unparseable content (so it isn't silently lost).
    """
    if not content:
        return ""
    parsed = _as_content_dict(content)
    if parsed is None:
        # Unparseable JSON string — surface it verbatim rather than dropping.
        return content if isinstance(content, str) else str(content)

    delta = parsed.get("deltaFormat")
    if isinstance(delta, list):
        pieces = [d.get("insert", "") for d in delta if isinstance(d, dict)]
        return "".join(pieces)

    for key in ("text", "value", "plainText"):
        val = parsed.get(key)
        if isinstance(val, str):
            return val
    return ""


def _extract_checked(content: Any) -> bool:
    """True if a check_list block's content carries `checked: true`.

    monday omits the key (or sets it to false) for unchecked items; an
    unchecked block has no `checked` field at all in the live API output.
    """
    parsed = _as_content_dict(content)
    return bool(parsed.get("checked")) if parsed else False


def collect_image_asset_ids(blocks: list[dict[str, Any]]) -> list[int]:
    """Asset IDs of every `image` block, in document order, de-duplicated.

    Markdown export resolves + downloads these before rendering. An image
    block carries its numeric `assetId` in `content`; the sibling `url` is a
    protected_static link that only works in a logged-in browser, so callers
    swap it for a pre-signed asset URL / downloaded file.
    """
    ids: list[int] = []
    for block in blocks:
        if _normalize_type(block.get("type") or "") != "image":
            continue
        content = _as_content_dict(block.get("content")) or {}
        aid = content.get("assetId")
        if isinstance(aid, bool):
            continue
        if isinstance(aid, int):
            ids.append(aid)
        elif isinstance(aid, str) and aid.isdigit():
            ids.append(int(aid))
    return list(dict.fromkeys(ids))


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
        "check_list",
        "quote",
        "code",
        "normal_text",
    }
)


def _render_image(
    block: dict[str, Any],
    images: dict[str, tuple[str, str]] | None,
    text_filter: Callable[[str], str] | None = None,
) -> str:
    """`![alt](ref)` for an `image` block.

    With an `images` map the asset's downloaded local filename (ref) and name
    (alt) replace the browser-only monday `url`; without it the `url` is kept
    so the image isn't silently dropped.
    """
    content = _as_content_dict(block.get("content")) or {}
    asset_id = content.get("assetId")
    alt = ""
    ref = content.get("url") or ""
    if images is not None and asset_id is not None:
        entry = images.get(str(asset_id))
        if entry is not None:
            alt, ref = entry
    if text_filter is not None:
        alt = text_filter(alt)
    # Escape `]` so an asset name like "a]b.png" can't close the alt span
    # early and corrupt the surrounding markdown.
    return f"![{alt.replace(']', r'\]')}]({ref})"


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


def _build_block_tree(
    blocks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Split the flat `parent_block_id` graph into `(roots, children_of)`.

    A block is a root when it has no parent, its parent is missing from this
    list (orphan — surfaced at top level so it's never silently dropped), or it
    points at itself (self-cycle). Shared by the markdown and HTML renderers.
    """
    by_id = {str(b["id"]): b for b in blocks if b.get("id") is not None}
    children_of: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    for b in blocks:
        parent = b.get("parent_block_id")
        bid = b.get("id")
        if parent is None or str(parent) == str(bid) or str(parent) not in by_id:
            roots.append(b)
        else:
            children_of.setdefault(str(parent), []).append(b)
    return roots, children_of


def blocks_to_markdown(
    blocks: list[dict[str, Any]],
    images: dict[str, tuple[str, str]] | None = None,
    text_filter: Callable[[str], str] | None = None,
) -> str:
    """Render a list of monday doc blocks as a markdown string.

    Walks the parent→children tree implied by `parent_block_id` so container
    blocks (notice/callout/layout/table) render with their inner content
    nested underneath, instead of children being detached and rendered out
    of context (issue #1).

    `images` maps `str(assetId)` → `(alt_text, ref)`; when an `image` block's
    asset is in the map its `ref` (a downloaded local filename) is emitted
    instead of the browser-only monday `url`.

    `text_filter`, when given, post-processes every piece of *prose* text
    (titles, list items, quotes, paragraphs, table cells, image alt) — code
    block contents are passed through untouched. `blocks_to_mdx` uses it to
    escape JSX-significant characters; markdown callers leave it `None`.
    """
    if not blocks:
        return ""

    roots, children_of = _build_block_tree(blocks)
    lines: list[str] = []
    _render_block_list(roots, children_of, "", lines, images, text_filter)
    return "\n".join(lines).rstrip() + "\n"


def _render_table(
    block: dict[str, Any],
    children_of: dict[str, list[dict[str, Any]]],
    prefix: str,
    lines: list[str],
    images: dict[str, tuple[str, str]] | None = None,
    text_filter: Callable[[str], str] | None = None,
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
    content = _as_content_dict(block.get("content"))
    if content is None:
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
                if _normalize_type(child.get("type") or "") == "image":
                    pieces.append(_render_image(child, images, text_filter))
                    continue
                t = _extract_text(child.get("content"))
                if t:
                    pieces.append(text_filter(t) if text_filter else t)
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
    images: dict[str, tuple[str, str]] | None = None,
    text_filter: Callable[[str], str] | None = None,
) -> None:
    """Render a sibling group at indentation `prefix`.

    Numbered-list counter is local to this call — a `1. … 2. …` list inside
    a notice restarts at 1 independently of any list outside it.
    """
    numbered_counter = 0
    for block in siblings:
        btype = _normalize_type(block.get("type") or "")
        text = _extract_text(block.get("content"))
        # Prose text is filtered (e.g. MDX escaping); code content is not —
        # MDX never parses inside a fenced code block.
        ptext = text_filter(text) if text_filter else text
        bid = str(block.get("id") or "")
        kids = children_of.get(bid, [])

        if btype != "numbered_list":
            numbered_counter = 0

        if btype == "table" and _render_table(
            block, children_of, prefix, lines, images, text_filter
        ):
            continue

        marker = _container_marker(btype, has_children=bool(kids))
        if marker is not None:
            child_prefix = prefix + "> " if marker else prefix
            if marker:
                lines.append(f"{prefix}> {marker}")
            _render_block_list(kids, children_of, child_prefix, lines, images, text_filter)
            lines.append("")
            continue

        # Leaf rendering.
        if btype == "divider":
            lines.append(f"{prefix}---")
        elif btype == "large_title":
            lines.append(f"{prefix}# {ptext}")
        elif btype == "medium_title":
            lines.append(f"{prefix}## {ptext}")
        elif btype == "small_title":
            lines.append(f"{prefix}### {ptext}")
        elif btype == "bulleted_list":
            lines.append(f"{prefix}- {ptext}")
        elif btype == "numbered_list":
            numbered_counter += 1
            lines.append(f"{prefix}{numbered_counter}. {ptext}")
        elif btype == "check_list":
            mark = "x" if _extract_checked(block.get("content")) else " "
            lines.append(f"{prefix}- [{mark}] {ptext}")
        elif btype == "quote":
            lines.append(f"{prefix}> {ptext}")
        elif btype == "code":
            content = _as_content_dict(block.get("content")) or {}
            lang = content.get("language", "")
            lines.append(f"{prefix}```{lang}")
            if text:
                lines.append(f"{prefix}{text}")
            lines.append(f"{prefix}```")
        elif btype == "image":
            lines.append(f"{prefix}{_render_image(block, images, text_filter)}")
        elif ptext:
            # normal_text + any other leaf type we haven't taught.
            lines.append(f"{prefix}{ptext}")

        # Defensive: a leaf block with unexpected children would otherwise
        # drop them. Render at same prefix so content survives.
        if kids:
            _render_block_list(kids, children_of, prefix, lines, images, text_filter)

        lines.append("")


# --- blocks → MDX -----------------------------------------------------------


def _mdx_escape(text: str) -> str:
    """Escape characters MDX would otherwise parse as JSX.

    MDX treats `<` as the start of a JSX element and `{` as the start of a JS
    expression; an unescaped one in plain prose is a hard compile error, not a
    cosmetic glitch. Backslash is escaped first so we don't double-process the
    escapes we add. Code-block contents are never passed here (see
    `blocks_to_markdown`'s `text_filter` contract).
    """
    return text.replace("\\", "\\\\").replace("<", r"\<").replace("{", r"\{")


# MDX parses a line that begins (after up to 3 spaces) with `import`/`export`
# as an ESM statement, so doc prose starting with either word would be compiled
# as module code instead of rendered as text — a hard failure, not cosmetic. A
# 4+ space indent is an indented code block, not ESM, so it's excluded.
_MDX_ESM_LINE_RE = re.compile(r"^( {0,3})(import|export)\b")

# A fenced-code opener, regardless of info string. Unlike `_CODE_FENCE_RE`
# (whose `[\w-]*` info string misses `c++`, `c#`, etc.), this recognizes any
# ``` or ~~~ run so fence tracking can't desync and rewrite real code as prose.
_MDX_FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _neutralize_mdx_esm(md: str) -> str:
    """Stop a prose line that opens with `import`/`export` from being parsed as
    MDX ESM by encoding its leading letter as a numeric character reference:
    the line no longer starts with the bare keyword, but renders identically.
    Fenced code blocks are left untouched — a fence closes only on a run of the
    *same* delimiter char (length ≥ the opener), so e.g. a `~~~` line inside a
    ```` ``` ```` block doesn't prematurely end tracking (GFM rule)."""
    out: list[str] = []
    fence_char = ""  # "" when outside a fence; "`" or "~" inside one
    fence_len = 0
    for line in md.split("\n"):
        if fence_char:
            stripped = line.strip()
            if stripped and stripped == fence_char * len(stripped) and len(stripped) >= fence_len:
                fence_char, fence_len = "", 0
            out.append(line)
            continue
        opener = _MDX_FENCE_OPEN_RE.match(line)
        if opener:
            fence_char = opener.group(1)[0]
            fence_len = len(opener.group(1))
            out.append(line)
            continue
        m = _MDX_ESM_LINE_RE.match(line)
        if m:
            kw = m.group(2)
            line = f"{m.group(1)}&#{ord(kw[0])};{kw[1:]}{line[m.end() :]}"
        out.append(line)
    return "\n".join(out)


def blocks_to_mdx(
    blocks: list[dict[str, Any]],
    images: dict[str, tuple[str, str]] | None = None,
) -> str:
    """Render doc blocks as MDX.

    MDX is GitHub-flavored markdown plus JSX, so the output is the markdown
    rendering with JSX-significant characters escaped in prose. monday's
    notice/callout containers stay as GFM `> [!NOTE]` blockquotes — MDX renders
    them as ordinary blockquotes, and we make no assumption about the caller's
    component library. A prose line opening with `import`/`export` is
    neutralized so MDX doesn't compile it as an ESM statement.
    """
    return _neutralize_mdx_esm(blocks_to_markdown(blocks, images=images, text_filter=_mdx_escape))


# --- blocks → HTML ----------------------------------------------------------

_HTML_STYLE = """\
:root { color-scheme: light dark; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.6; max-width: 48rem; margin: 2rem auto; padding: 0 1rem;
  color: #1a1a1a;
}
h1, h2, h3 { line-height: 1.25; margin: 1.4em 0 0.5em; }
h1.doc-title { margin-top: 0; }
img { max-width: 100%; height: auto; }
hr { border: none; border-top: 1px solid #ddd; margin: 1.5em 0; }
blockquote {
  margin: 1em 0; padding: 0.2em 1em; border-left: 4px solid #ddd; color: #555;
}
pre {
  background: #f5f5f5; padding: 0.8em 1em; border-radius: 6px; overflow-x: auto;
}
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.9em; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #ddd; padding: 0.4em 0.7em; text-align: left; }
th { background: #f5f5f5; }
ul.checklist { list-style: none; padding-left: 1.2em; }
ul.checklist li { text-indent: -1.2em; }
aside.notice {
  margin: 1em 0; padding: 0.8em 1em; border-left: 4px solid #4a90d9;
  background: #eef5fc; border-radius: 0 6px 6px 0;
}
.layout { display: flow-root; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e6e6; background: #1a1a1a; }
  pre, th { background: #2a2a2a; }
  blockquote, hr, th, td { border-color: #444; }
  aside.notice { background: #16283a; }
}
/* Print / PDF export (issue #68): WeasyPrint renders print media, so force
   light colors, drop the on-screen centering, wrap long code, and keep small
   blocks and table rows from splitting across pages. */
@page { size: A4; margin: 1.6cm; }
@media print {
  body { max-width: none; margin: 0; padding: 0; color: #000; background: #fff; font-size: 10.5pt; }
  pre, code { font-size: 8.5pt; }
  pre { white-space: pre-wrap; word-wrap: break-word; }
  pre, blockquote, aside.notice, tr, img { break-inside: avoid; }
  h1, h2, h3 { break-after: avoid; }
}
"""


def _html_text(content: Any) -> str:
    """Extract a block's text and HTML-escape it."""
    return html.escape(_extract_text(content))


def _render_html_image(block: dict[str, Any], images: dict[str, tuple[str, str]] | None) -> str:
    """`<img>` for an image block; `src` is the embedded data URI (or, without
    a map, the browser-only monday url so the image isn't dropped)."""
    content = _as_content_dict(block.get("content")) or {}
    asset_id = content.get("assetId")
    alt = ""
    src = content.get("url") or ""
    if images is not None and asset_id is not None:
        entry = images.get(str(asset_id))
        if entry is not None:
            alt, src = entry
    return f'<img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}">'


def _render_html_table(
    block: dict[str, Any],
    children_of: dict[str, list[dict[str, Any]]],
    images: dict[str, tuple[str, str]] | None,
) -> list[str] | None:
    """Render a `table` block as an HTML `<table>`.

    Mirrors `_render_table`'s reading of `content.cells` (a row-major matrix of
    `{"blockId": ...}` references). Returns None when the schema is
    missing/malformed so the caller can fall back to a generic container.
    """
    content = _as_content_dict(block.get("content"))
    if content is None:
        return None
    cells_matrix = content.get("cells")
    if not isinstance(cells_matrix, list) or not cells_matrix:
        return None

    grid: list[list[str]] = []
    for row in cells_matrix:
        if not isinstance(row, list):
            return None
        row_html: list[str] = []
        for cell_ref in row:
            cell_id = ""
            if isinstance(cell_ref, dict) and cell_ref.get("blockId") is not None:
                cell_id = str(cell_ref["blockId"])
            pieces: list[str] = []
            for child in children_of.get(cell_id, []):
                if _normalize_type(child.get("type") or "") == "image":
                    pieces.append(_render_html_image(child, images))
                else:
                    t = _html_text(child.get("content"))
                    if t:
                        pieces.append(t)
            row_html.append(" ".join(pieces))
        grid.append(row_html)

    if not grid or not grid[0]:
        return None
    col_count = max(len(row) for row in grid)
    grid = [row + [""] * (col_count - len(row)) for row in grid]

    out = ["<table>", "<thead><tr>"]
    out += [f"<th>{c}</th>" for c in grid[0]]
    out.append("</tr></thead>")
    out.append("<tbody>")
    for row in grid[1:]:
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>")
    out += ["</tbody>", "</table>"]
    return out


_HTML_HEADINGS = {"large_title": "h1", "medium_title": "h2", "small_title": "h3"}
_HTML_LIST_TYPES = ("bulleted_list", "numbered_list", "check_list")


def _render_html_blocks(
    siblings: list[dict[str, Any]],
    children_of: dict[str, list[dict[str, Any]]],
    images: dict[str, tuple[str, str]] | None,
) -> list[str]:
    """Render a sibling group to HTML fragment lines.

    Consecutive list items of the same type are grouped into one `<ul>`/`<ol>`,
    which the line-oriented markdown renderer doesn't need to do.
    """
    out: list[str] = []
    i = 0
    n = len(siblings)
    while i < n:
        block = siblings[i]
        btype = _normalize_type(block.get("type") or "")
        if btype in _HTML_LIST_TYPES:
            tag = "ol" if btype == "numbered_list" else "ul"
            cls = ' class="checklist"' if btype == "check_list" else ""
            out.append(f"<{tag}{cls}>")
            while i < n and _normalize_type(siblings[i].get("type") or "") == btype:
                out.append(_render_html_list_item(siblings[i], btype, children_of, images))
                i += 1
            out.append(f"</{tag}>")
            continue
        out += _render_html_block(block, children_of, images)
        i += 1
    return out


def _render_html_list_item(
    block: dict[str, Any],
    btype: str,
    children_of: dict[str, list[dict[str, Any]]],
    images: dict[str, tuple[str, str]] | None,
) -> str:
    text = _html_text(block.get("content"))
    if btype == "check_list":
        # Inline box glyph (U+2611 ☑ / U+2610 ☐) rather than `<input
        # type=checkbox>`: WeasyPrint renders a replaced form control as its own
        # block, pushing the label onto the next line in PDF export. A glyph is
        # plain inline text that lays out identically in browsers and WeasyPrint
        # (the control was `disabled`/non-interactive anyway).
        box = "☑" if _extract_checked(block.get("content")) else "☐"
        text = f"{box} {text}"
    kids = children_of.get(str(block.get("id") or ""), [])
    inner = "".join(_render_html_blocks(kids, children_of, images)) if kids else ""
    return f"<li>{text}{inner}</li>"


def _render_html_block(
    block: dict[str, Any],
    children_of: dict[str, list[dict[str, Any]]],
    images: dict[str, tuple[str, str]] | None,
) -> list[str]:
    """Render a single non-list block to HTML fragment lines."""
    btype = _normalize_type(block.get("type") or "")
    bid = str(block.get("id") or "")
    kids = children_of.get(bid, [])
    text = _html_text(block.get("content"))

    if btype == "table":
        table = _render_html_table(block, children_of, images)
        if table is not None:
            return table
        # malformed schema → fall through to the generic container below.

    marker = _container_marker(btype, has_children=bool(kids))
    if marker is not None:
        inner = _render_html_blocks(kids, children_of, images)
        if btype in ("notice_box", "notice", "callout"):
            return ['<aside class="notice">', *inner, "</aside>"]
        if btype == "layout":
            return ['<div class="layout">', *inner, "</div>"]
        return ['<div class="container">', *inner, "</div>"]

    if btype == "divider":
        return ["<hr>"]
    if btype in _HTML_HEADINGS:
        tag = _HTML_HEADINGS[btype]
        return [f"<{tag}>{text}</{tag}>"]
    if btype == "quote":
        return [f"<blockquote>{text}</blockquote>"]
    if btype == "code":
        content = _as_content_dict(block.get("content")) or {}
        lang = content.get("language", "")
        cls = f' class="language-{html.escape(lang, quote=True)}"' if lang else ""
        # Code text is escaped directly (not via _html_text) for clarity.
        return [f"<pre><code{cls}>{html.escape(_extract_text(content))}</code></pre>"]
    if btype == "image":
        out = [_render_html_image(block, images)]
    elif text:
        out = [f"<p>{text}</p>"]
    else:
        out = []

    # Defensive: a leaf with unexpected children — render them rather than drop.
    if kids:
        out += _render_html_blocks(kids, children_of, images)
    return out


def blocks_to_html(
    blocks: list[dict[str, Any]],
    images: dict[str, tuple[str, str]] | None = None,
    title: str | None = None,
) -> str:
    """Render doc blocks as a single self-contained HTML document.

    The result has an inline `<style>` and (when an `images` map of
    `str(assetId)` → `(alt, data-uri)` is supplied) base64-embedded images, so
    the file works offline with no sibling assets. Without the map, image
    `src`s keep their browser-only monday urls.
    """
    roots, children_of = _build_block_tree(blocks)
    body = _render_html_blocks(roots, children_of, images)
    doc_title = title or "Document"
    heading = f'<h1 class="doc-title">{html.escape(doc_title)}</h1>\n' if title else ""
    body_html = "\n".join(body)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(doc_title)}</title>\n"
        f"<style>\n{_HTML_STYLE}</style>\n</head>\n<body>\n"
        f"{heading}{body_html}\n</body>\n</html>\n"
    )
