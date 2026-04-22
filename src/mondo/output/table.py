"""Rich table formatter.

Rules (plan §11.2):
    - Array of objects → one row per element; columns = union of top-level keys.
    - Object          → two-column key/value.
    - Scalar          → printed as-is.
    - Nested values   → collapsed to `<list>` / `<object>` markers; the user
                        who wants the details should use `-o json -q ...`.
"""

from __future__ import annotations

from typing import Any, TextIO

_SCALAR_TYPES = (str, int, float, bool, type(None))


def _render_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, list):
        return f"<list:{len(value)}>"
    if isinstance(value, dict):
        return "<object>"
    return str(value)


def _array_of_dicts(data: list[Any]) -> bool:
    return bool(data) and all(isinstance(r, dict) for r in data)


def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    """Union of keys across rows, preserving first-seen order."""
    seen: dict[str, None] = {}
    for row in rows:
        for k in row:
            seen.setdefault(k, None)
    return list(seen)


def render(data: Any, stream: TextIO, tty: bool) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console(
        file=stream,
        force_terminal=tty,
        no_color=not tty,
        highlight=False,
        width=None if tty else 200,
    )

    if isinstance(data, list):
        if not data:
            console.print("(empty)")
            return
        if _array_of_dicts(data):
            columns = _ordered_columns(data)
            table = Table(show_header=True, header_style="bold cyan")
            for col in columns:
                table.add_column(col)
            for row in data:
                table.add_row(*(_render_cell(row.get(col)) for col in columns))
            console.print(table)
            return
        # Array of scalars → single-column table
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("value")
        for item in data:
            table.add_row(_render_cell(item))
        console.print(table)
        return

    if isinstance(data, dict):
        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column(style="cyan")
        table.add_column()
        for k, v in data.items():
            table.add_row(str(k), _render_cell(v))
        console.print(table)
        return

    # Scalar
    if data is None:
        return
    console.print(_render_cell(data))
