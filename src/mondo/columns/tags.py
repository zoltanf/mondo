"""Tags column codec.

The codec itself handles only integer IDs. Name → ID resolution happens at
the CLI layer (which can call `create_or_get_tag`). If a user passes names
here, we raise with a pointer to the resolution helper.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register


class TagsCodec(ColumnCodec):
    type_name: ClassVar[str] = "tags"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, list[int]]:
        stripped = value.strip()
        if not stripped:
            return {}

        parts = [p.strip() for p in stripped.split(",") if p.strip()]
        try:
            ids = [int(p) for p in parts]
        except ValueError as e:
            raise ValueError(
                f"tags codec accepts integer IDs only (got {stripped!r}). "
                f"To use tag names, the CLI resolves them via "
                f"`create_or_get_tag(tag_name, board_id)` before calling parse; "
                f'call `mondo graphql \'mutation {{ create_or_get_tag(tag_name: "name", '
                f"board_id: N) {{ id }} }}'` to look them up manually."
            ) from e
        return {"tag_ids": ids}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


register(TagsCodec())
