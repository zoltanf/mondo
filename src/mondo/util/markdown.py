"""Markdown → HTML conversion for monday update bodies.

monday's `create_update` / `edit_update` mutations only accept HTML. Users
writing updates from shell one-liners or markdown files prefer writing
markdown; we convert with `markdown-it-py` (pure Python, CommonMark-spec,
no raw-HTML passthrough by default) so copy-pasting from a markdown file
Just Works.
"""

from __future__ import annotations

from markdown_it import MarkdownIt

# CommonMark preset; raw HTML passthrough is off by default which is what we
# want — users should write monday-specific HTML (e.g. `<mention>`) via the
# --body path without --markdown, not mixed into markdown input.
_MD = MarkdownIt("commonmark")


def to_html(text: str) -> str:
    """Render CommonMark markdown to HTML suitable for monday's update body."""
    rendered: str = _MD.render(text)
    return rendered
