"""ColumnCodec base class and registry.

Each codec owns:
- `parse(value, settings)`: turn user shorthand → monday's JSON write shape.
- `render(value, text)`: turn monday's read payload → human-readable string.
- `clear_payload()`: what to send to clear the column (default `{}`;
  monday-api.md §11.6 lists the exceptions).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar


class UnknownColumnTypeError(KeyError):
    """Raised when a column type has no registered codec."""


class ColumnCodec(ABC):
    """Base class — subclasses set `type_name` and implement parse/render."""

    type_name: ClassVar[str]

    @abstractmethod
    def parse(self, value: str, settings: dict[str, Any]) -> Any:
        """Convert user-supplied shorthand into monday's write shape.

        `settings` is the parsed `settings_str` JSON from the column (needed
        by status/dropdown/tags/etc. to resolve labels ↔ ids).
        """

    @abstractmethod
    def render(self, value: Any, text: str | None) -> str:
        """Convert a column_values entry into a human-friendly display."""

    def render_entry(self, entry: dict[str, Any]) -> str:
        """Render a full ``column_values`` entry dict (id/type/text/value + any
        polymorphic fields like ``display_value``/``linked_item_ids``).

        Default: parse the JSON ``value`` and delegate to
        ``render(value, text)``. Codecs whose read payload only surfaces via an
        inline fragment (mirror, board_relation) override this to read those
        fields straight off the entry.
        """
        text = entry.get("text")
        raw = entry.get("value")
        value: Any = None
        if raw:
            try:
                value = json.loads(raw)
            except ValueError:
                value = raw
        return self.render(value, text)

    def clear_payload(self) -> Any:
        """Override when the column doesn't clear with `{}` (checkbox, file, ...)."""
        return {}

    def parse_filter(self, value: str, settings: dict[str, Any]) -> list[Any]:
        """Turn `--filter COL=raw` into the `compare_value` list monday wants.

        The mutation `parse()` shape and the filter `compare_value` shape are
        *not* the same: filter rules want a flat list of scalars (strings for
        text/numbers/date, **integer indices** for status, **integer option
        ids** for dropdown), while mutations want full objects like
        ``{"label": "Done"}``.

        Default: split on commas, send strings. Override per codec when the
        column has settings-driven label→id resolution.
        """
        return [v.strip() for v in value.split(",")]


_REGISTRY: dict[str, ColumnCodec] = {}


def register(codec: ColumnCodec) -> None:
    """Register a codec. Safe to call multiple times with the same codec."""
    _REGISTRY[codec.type_name] = codec


def get_codec(type_name: str) -> ColumnCodec:
    try:
        return _REGISTRY[type_name]
    except KeyError as e:
        raise UnknownColumnTypeError(
            f"no codec registered for column type {type_name!r}; known types: {sorted(_REGISTRY)}"
        ) from e


class LabelAwareCodec(ColumnCodec):
    """Base for codecs whose labels can be server-created on the fly.

    ``create_labels=True`` mirrors the mutation's ``create_labels_if_missing``
    flag and tells the codec to skip its client-side reject of unknown labels
    so the server can create them.
    """

    @abstractmethod
    def parse(
        self, value: str, settings: dict[str, Any], *, create_labels: bool = False
    ) -> Any: ...

    def _resolve_label_csv(
        self,
        value: str,
        *,
        name_to_id: dict[str, int],
        escape_prefix: str,
        escape_resolver: Callable[[str], int],
        label_kind: str,
    ) -> list[int]:
        """Shared `parse_filter` loop for status / dropdown.

        - `name_to_id` maps the user-visible label to the integer id.
        - `escape_prefix` is the literal id-escape (e.g. "#" or "id:").
        - `escape_resolver` parses one escaped token (without the prefix) into
          an int; it may raise ValueError with a kind-specific message.
        - `label_kind` is "status"/"dropdown" — used only in the unknown-label
          error.
        """
        out: list[int] = []
        for raw in value.split(","):
            token = raw.strip()
            if not token:
                continue
            if token.lower().startswith(escape_prefix):
                out.append(escape_resolver(token[len(escape_prefix) :]))
                continue
            if token in name_to_id:
                out.append(name_to_id[token])
                continue
            known = ", ".join(name_to_id) if name_to_id else "(no labels known)"
            raise ValueError(f"unknown {label_kind} label {token!r}. Known: {known}")
        return out


def parse_value(
    type_name: str,
    value: str,
    settings: dict[str, Any],
    *,
    create_labels: bool = False,
) -> Any:
    codec = get_codec(type_name)
    if isinstance(codec, LabelAwareCodec):
        return codec.parse(value, settings, create_labels=create_labels)
    return codec.parse(value, settings)


def parse_filter_value(
    type_name: str,
    value: str,
    settings: dict[str, Any],
) -> list[Any]:
    """Codec dispatch for filter `compare_value`.

    Raises ``UnknownColumnTypeError`` for types without a registered codec —
    caller should fall back to a raw string list to preserve today's behavior
    for niche column types.
    """
    return get_codec(type_name).parse_filter(value, settings)


def render_value(type_name: str, value: Any, text: str | None) -> str:
    return get_codec(type_name).render(value, text)


def render_entry(type_name: str, entry: dict[str, Any]) -> str:
    """Render a full ``column_values`` entry via its codec's ``render_entry``.

    Prefer this over ``render_value`` at read sites: it lets mirror, formula,
    board_relation & dependency codecs surface ``display_value`` from the
    polymorphic inline fragments.
    """
    return get_codec(type_name).render_entry(entry)


def clear_payload_for(type_name: str) -> Any:
    return get_codec(type_name).clear_payload()


def registered_types() -> list[str]:
    return sorted(_REGISTRY)
