"""Dropdown column codec.

Shorthand:
    `Cookie,Cupcake`    → write by label
    `id:1,2`            → write by id
    ``                  → clear
"""

from __future__ import annotations

from typing import Any, ClassVar

from mondo.columns.base import ColumnCodec, register


class DropdownCodec(ColumnCodec):
    type_name: ClassVar[str] = "dropdown"

    def parse(self, value: str, settings: dict[str, Any]) -> dict[str, Any]:
        stripped = value.strip()
        if not stripped:
            return {}

        if stripped.lower().startswith("id:"):
            id_part = stripped[3:]
            try:
                ids = [int(x.strip()) for x in id_part.split(",") if x.strip()]
            except ValueError as e:
                raise ValueError(f"dropdown ids must be integer, got {id_part!r}") from e
            return {"ids": ids}

        labels = [x.strip() for x in stripped.split(",") if x.strip()]
        known = _known_labels(settings)
        if known is not None:
            unknown = [x for x in labels if x not in known]
            if unknown:
                raise ValueError(
                    f"unknown dropdown label(s): {unknown!r}. "
                    f"Known: {sorted(known)}. "
                    f"Use --create-labels-if-missing to add on the fly."
                )
        return {"labels": labels}

    def render(self, value: Any, text: str | None) -> str:
        return text or ""


def _known_labels(settings: dict[str, Any]) -> set[str] | None:
    """Extract known labels from settings_str. Returns None if unknown/empty."""
    labels = settings.get("labels")
    if not labels:
        return None
    if isinstance(labels, list):
        # modern shape: [{id, name}, ...]
        return {item["name"] for item in labels if isinstance(item, dict) and "name" in item}
    if isinstance(labels, dict):
        # legacy shape: {"1": "Cookie", ...} — same as status
        return {str(v) for v in labels.values()}
    return None


register(DropdownCodec())
