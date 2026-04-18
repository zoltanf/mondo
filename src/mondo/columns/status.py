"""Status column codec.

Users write `Done` (label) or `#1` (index).
Plan §9 and monday-api.md §11.5.4 recommend `index` for stability (labels can
be renamed) but labels are more intuitive on the CLI — we accept both.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register


class StatusCodec(ColumnCodec):
    type_name: ClassVar[str] = "status"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, Any]:
        stripped = value.strip()
        if not stripped:
            return {}  # clear

        if stripped.startswith("#"):
            idx_str = stripped[1:]
            try:
                idx = int(idx_str)
            except ValueError as e:
                raise ValueError(f"invalid status index {stripped!r}: use format #N") from e
            labels = settings.get("labels") or {}
            if labels and str(idx) not in labels:
                allowed = ", ".join(sorted(labels.keys()))
                raise ValueError(f"status index {idx} out of range. Valid indices: {allowed}")
            return {"index": idx}

        # Treat as label. If we have settings, validate — else accept.
        labels = settings.get("labels") or {}
        if labels and stripped not in labels.values():
            known = ", ".join(sorted(labels.values()))
            raise ValueError(
                f"unknown status label {stripped!r}. "
                f"Known: {known}. "
                f"Use --create-labels-if-missing to add it on the fly."
            )
        return {"label": stripped}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


register(StatusCodec())
