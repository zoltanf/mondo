"""Tests for read-only column codecs.

These are types that can be read but never written via column_values.
`parse` raises; `render` works off `text`.
"""

from __future__ import annotations

import pytest

from mondo.columns import (
    UnknownColumnTypeError,
    parse_value,
    readonly,  # noqa: F401
    render_value,
)

READ_ONLY_TYPES = [
    "mirror",
    "formula",
    "auto_number",
    "item_id",
    "creation_log",
    "last_updated",
    "color_picker",
    "progress",
    "time_tracking",
    "vote",
    "button",
    "subtasks",
]


@pytest.mark.parametrize("type_name", READ_ONLY_TYPES)
def test_parse_raises(type_name: str) -> None:
    with pytest.raises(ValueError, match="read-only"):
        parse_value(type_name, "anything", {})


@pytest.mark.parametrize("type_name", READ_ONLY_TYPES)
def test_render_from_text(type_name: str) -> None:
    assert render_value(type_name, {}, "display") == "display"


@pytest.mark.parametrize("type_name", READ_ONLY_TYPES)
def test_render_empty(type_name: str) -> None:
    assert render_value(type_name, None, None) == ""


def test_truly_unknown_type_still_raises_unknown() -> None:
    """A type not in any registered module stays undiscoverable."""
    with pytest.raises(UnknownColumnTypeError):
        parse_value("some_made_up_type", "x", {})
