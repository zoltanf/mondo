"""Output rendering for the CLI layer.

Extracted from ``GlobalOpts.emit`` so the render pipeline (``--query`` →
``--fields`` → format) is a plain function that can be unit-tested with a
``StringIO`` stream. ``GlobalOpts.emit`` is now a thin wrapper that forwards
its parsed flags here and folds the returned ``wrote`` boolean back into
``self.stdout_emitted``.
"""

from __future__ import annotations

import os
import sys
from typing import Any, TextIO


def render_output(
    data: Any,
    *,
    output: str | None,
    query: str | None,
    fields: str | None,
    stream: TextIO | None = None,
    default_tty_override: bool | None = None,
    selected_fields: frozenset[str] | None = None,
) -> bool:
    """Render ``data`` honoring ``--output`` / ``--query`` / ``--fields``.

    Applies ``--query`` before formatting. Auto-picks the format based on
    whether stdout is a TTY if ``output`` wasn't set.

    When ``selected_fields`` is provided alongside ``query``, every JMESPath
    leaf identifier missing from the set produces one stderr warning line —
    this is how silent-null projections (a leaf the GraphQL query never
    selected) become visible. Set ``MONDO_NO_PROJECTION_WARNINGS=1`` to
    suppress.

    Returns ``True`` iff it wrote to real stdout (``stream is None`` and the
    resolved format is not ``none``). Callers use this to track whether a
    partial-success stream has already been committed.
    """
    out = stream or sys.stdout
    is_tty = (
        default_tty_override
        if default_tty_override is not None
        else hasattr(out, "isatty") and out.isatty()
    )
    from mondo.output import choose_default_format, format_output
    from mondo.output.fields import apply_fields
    from mondo.output.query import apply_query

    fmt = output or choose_default_format(is_tty=is_tty)
    try:
        projected = apply_query(data, query)
    except ValueError as e:
        from mondo.cli._exec import usage_error_or_exit

        usage_error_or_exit(str(e))
    projected = apply_fields(projected, fields)
    if (
        query
        and selected_fields is not None
        and os.environ.get("MONDO_NO_PROJECTION_WARNINGS") != "1"
    ):
        warn_unselected_projection_fields(query, selected_fields)
    format_output(projected, fmt=fmt, stream=out, tty=is_tty)
    return stream is None and fmt != "none"


def warn_unselected_projection_fields(expression: str, selected_fields: frozenset[str]) -> None:
    import typer

    from mondo.output.query import extract_query_leaf_fields

    leaves = extract_query_leaf_fields(expression)
    for missing in sorted(leaves - selected_fields):
        typer.secho(
            f"warning: field '{missing}' is not in the GraphQL selection set",
            fg=typer.colors.YELLOW,
            err=True,
        )
