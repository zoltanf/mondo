"""Output formatters.

Public surface:
    format_output(data, fmt, stream, tty=False) — render in the requested format
    choose_default_format(is_tty)             — az-style auto-detection
    AVAILABLE_FORMATS                         — set of valid format names
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TextIO

from mondo.output import csv_, json_, jsonc, none_, table, tsv, yaml_

Formatter = Callable[[Any, TextIO, bool], None]


_REGISTRY: dict[str, Formatter] = {
    "json": json_.render,
    "jsonc": jsonc.render,
    "yaml": yaml_.render,
    "csv": csv_.render,
    "tsv": tsv.render,
    "none": none_.render,
    "table": table.render,
}

AVAILABLE_FORMATS: frozenset[str] = frozenset(_REGISTRY)


def format_output(
    data: Any,
    *,
    fmt: str,
    stream: TextIO,
    tty: bool = False,
) -> None:
    """Render `data` to `stream` in `fmt`.

    `tty` hints formatters that support colorization (jsonc, table) whether
    the destination is a terminal. Non-terminal streams get plain output.
    """
    try:
        renderer = _REGISTRY[fmt]
    except KeyError as e:
        raise ValueError(f"unknown format {fmt!r}; choose from {sorted(AVAILABLE_FORMATS)}") from e
    renderer(data, stream, tty)


def choose_default_format(is_tty: bool) -> str:
    """Pick the default format based on destination (az-style)."""
    return "table" if is_tty else "json"
