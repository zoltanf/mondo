"""Read-only column renderers.

These types (mirror, formula, auto_number, item_id, creation_log,
last_updated, color_picker, progress, time_tracking, vote, button, subtasks)
cannot be written through `column_values` (monday-api.md §11.5.24). The
codec's `parse` raises; `render` uses the `text` field that monday returns.

Each type gets its own class primarily so `registered_types()` includes them
and so future polymorphic rendering (e.g. mirror's `display_value` via an
inline fragment) can hook in per-type.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register


class _ReadOnly(ColumnCodec):
    """Common base for read-only types."""

    def parse(self, value: str, settings: dict[str, Any]) -> Any:
        raise ValueError(f"column type {self.type_name!r} is read-only; cannot be set via the API")

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


class MirrorCodec(_ReadOnly):
    type_name: ClassVar[str] = "mirror"


class FormulaCodec(_ReadOnly):
    type_name: ClassVar[str] = "formula"


class AutoNumberCodec(_ReadOnly):
    type_name: ClassVar[str] = "auto_number"


class ItemIdCodec(_ReadOnly):
    type_name: ClassVar[str] = "item_id"


class CreationLogCodec(_ReadOnly):
    type_name: ClassVar[str] = "creation_log"


class LastUpdatedCodec(_ReadOnly):
    type_name: ClassVar[str] = "last_updated"


class ColorPickerCodec(_ReadOnly):
    type_name: ClassVar[str] = "color_picker"


class ProgressCodec(_ReadOnly):
    type_name: ClassVar[str] = "progress"


class TimeTrackingCodec(_ReadOnly):
    type_name: ClassVar[str] = "time_tracking"


class VoteCodec(_ReadOnly):
    type_name: ClassVar[str] = "vote"


class ButtonCodec(_ReadOnly):
    type_name: ClassVar[str] = "button"


class SubtasksCodec(_ReadOnly):
    """The `subtasks` column surfaces subitems read-only; writes go through
    `create_subitem` (phase 3)."""

    type_name: ClassVar[str] = "subtasks"


class FileCodec(ColumnCodec):
    """File columns cannot be written via `column_values` — uploads require
    the multipart `/v2/file` endpoint. `mondo column set` rejects with a
    pointer to the future `mondo file upload` command."""

    type_name: ClassVar[str] = "file"

    def parse(self, value: str, settings: dict[str, Any]) -> Any:
        raise ValueError(
            "file columns cannot be set via `column set`: file uploads require "
            "the multipart /v2/file endpoint. Use `mondo file upload` (coming "
            "in a later phase) or call it manually. To clear a file column, use "
            "`mondo column clear --item ... --column ...`."
        )

    def render(self, value: Any, text: str | None) -> str:
        return text or ""

    def clear_payload(self) -> dict[str, bool]:
        # Per monday-api.md §11.5.23: `{"clear_all": true}` clears the column.
        return {"clear_all": True}


for cls in (
    MirrorCodec,
    FormulaCodec,
    AutoNumberCodec,
    ItemIdCodec,
    CreationLogCodec,
    LastUpdatedCodec,
    ColorPickerCodec,
    ProgressCodec,
    TimeTrackingCodec,
    VoteCodec,
    ButtonCodec,
    SubtasksCodec,
    FileCodec,
):
    register(cls())
