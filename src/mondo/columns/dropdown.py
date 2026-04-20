"""Dropdown column codec.

Shorthand:
    `Cookie,Cupcake`    → write by label
    `id:1,2`            → write by id
    ``                  → clear
"""

from __future__ import annotations

from typing import Any, ClassVar

from mondo.columns.base import LabelAwareCodec, register


class DropdownCodec(LabelAwareCodec):
    type_name: ClassVar[str] = "dropdown"

    def parse(
        self, value: str, settings: dict[str, Any], *, create_labels: bool = False
    ) -> dict[str, Any]:
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
        if not create_labels:
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


def iter_dropdown_labels(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the dropdown's labels as ``[{id, name}, ...]``.

    Handles both shapes monday emits: the modern list-of-dicts and the legacy
    dict-keyed-by-index. Empty / unrecognised settings yield an empty list.
    """
    labels = settings.get("labels")
    if not labels:
        return []
    if isinstance(labels, list):
        return [
            {"id": item.get("id"), "name": item["name"]}
            for item in labels
            if isinstance(item, dict) and "name" in item
        ]
    if isinstance(labels, dict):
        return [{"id": int(idx), "name": str(name)} for idx, name in labels.items()]
    return []


def _known_labels(settings: dict[str, Any]) -> set[str] | None:
    """Extract known labels from settings_str. Returns None if unknown/empty."""
    entries = iter_dropdown_labels(settings)
    if not entries:
        return None
    return {str(e["name"]) for e in entries}


register(DropdownCodec())
