"""Fill null `text` from computed `display_value` before emitting typed reads.

monday returns `text: null` for computed column types (mirror, formula,
board_relation, dependency); their rendered value lives in the polymorphic
`display_value` field. Naive consumers read `.text`, see null, and conclude
the column is empty (#105) — so typed reads and item-shaped mutation
returns (create / column set) emit `text` filled from `display_value`.
`display_value` stays present, matching the fallback `export board`
already applies.
"""

from __future__ import annotations

from typing import Any


def fill_computed_text(rows: dict[str, Any] | list[dict[str, Any]] | None) -> None:
    """Mutate item dict(s) in place: `text = display_value` where text is null.

    Accepts a single item or a list of items; recurses into nested
    `subitems` (`item get --with-subitems` carries their column_values too).
    """
    if rows is None:
        return
    items = rows if isinstance(rows, list) else [rows]
    for item in items:
        if not isinstance(item, dict):
            continue
        for cv in item.get("column_values") or []:
            if not isinstance(cv, dict):
                continue
            display = cv.get("display_value")
            if cv.get("text") is None and isinstance(display, str) and display:
                cv["text"] = display
        subitems = item.get("subitems")
        if isinstance(subitems, list):
            fill_computed_text(subitems)
