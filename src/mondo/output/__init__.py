"""Output formatters.

Public surface:
    format_output(data, fmt, stream, tty=False) — render in the requested format
    choose_default_format(is_tty)             — az-style auto-detection
    AVAILABLE_FORMATS                         — set of valid format names
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any, TextIO

Formatter = Callable[[Any, TextIO, bool], None]

_MODULES: dict[str, str] = {
    "json": "mondo.output.json_",
    "jsonc": "mondo.output.jsonc",
    "yaml": "mondo.output.yaml_",
    "csv": "mondo.output.csv_",
    "tsv": "mondo.output.tsv",
    "none": "mondo.output.none_",
    "table": "mondo.output.table",
}

AVAILABLE_FORMATS: frozenset[str] = frozenset(_MODULES)
_FORMATTER_CACHE: dict[str, Formatter] = {}


def _resolve_formatter(fmt: str) -> Formatter:
    renderer = _FORMATTER_CACHE.get(fmt)
    if renderer is not None:
        return renderer
    try:
        module_name = _MODULES[fmt]
    except KeyError as e:
        raise ValueError(f"unknown format {fmt!r}; choose from {sorted(AVAILABLE_FORMATS)}") from e
    module = import_module(module_name)
    renderer = module.render
    _FORMATTER_CACHE[fmt] = renderer
    return renderer


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
    renderer = _resolve_formatter(fmt)
    renderer(data, stream, tty)


def choose_default_format(is_tty: bool) -> str:
    """Pick the default format based on destination (az-style)."""
    return "table" if is_tty else "json"
