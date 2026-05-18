"""Status column codec.

Users write `Done` (label) or `#1` (index).
Plan §9 and monday-api.md §11.5.4 recommend `index` for stability (labels can
be renamed) but labels are more intuitive on the CLI — we accept both.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mondo.columns.base import LabelAwareCodec, register


class StatusCodec(LabelAwareCodec):
    type_name: ClassVar[str] = "status"

    def parse(
        self, value: str, settings: dict[str, Any], *, create_labels: bool = False
    ) -> dict[str, Any]:
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

        if not create_labels:
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

    def parse_filter(self, value: str, settings: dict[str, Any]) -> list[int]:
        """Resolve `--filter status=<labels-or-#N>` to integer indices.

        monday's `items_page` rejects status filters silently when
        `compare_value` is a label string or a stringified index — it only
        matches when each entry is an integer index. Verified empirically
        against the live API on 2026-05-18.
        """
        labels_map = settings.get("labels") or {}
        # Build label → index mapping (case-sensitive, mirrors `parse()`).
        label_to_index: dict[str, int] = {}
        if isinstance(labels_map, dict):
            for idx_key, label in labels_map.items():
                try:
                    label_to_index[str(label)] = int(idx_key)
                except (TypeError, ValueError):
                    continue
        out: list[int] = []
        for raw in value.split(","):
            token = raw.strip()
            if not token:
                continue
            if token.startswith("#"):
                idx_str = token[1:]
                try:
                    idx = int(idx_str)
                except ValueError as e:
                    raise ValueError(
                        f"invalid status index {token!r}: use format #N"
                    ) from e
                if labels_map and str(idx) not in labels_map:
                    allowed = ", ".join(sorted(labels_map.keys()))
                    raise ValueError(
                        f"status index {idx} out of range. Valid indices: {allowed}"
                    )
                out.append(idx)
                continue
            if token in label_to_index:
                out.append(label_to_index[token])
                continue
            known = ", ".join(label_to_index) if label_to_index else "(no labels known)"
            raise ValueError(
                f"unknown status label {token!r}. Known: {known}"
            )
        return out


def iter_status_labels(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the status column's labels as ``[{index, label}, ...]`` sorted by index."""
    labels = settings.get("labels") or {}
    if not isinstance(labels, dict):
        return []
    pairs = sorted((int(idx), str(label)) for idx, label in labels.items())
    return [{"index": idx, "label": label} for idx, label in pairs]


register(StatusCodec())
