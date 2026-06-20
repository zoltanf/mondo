"""Business logic for the `mondo item` command group.

Query building, validation, and column-value rendering extracted from
:mod:`mondo.cli.item`. The Typer callbacks own argument parsing, emission,
polling, and exit-code mapping; everything here takes plain arguments,
returns plain data, and raises domain errors from :mod:`mondo.api.errors`.
"""

from __future__ import annotations

import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mondo.api.errors import NotFoundError, UsageError
from mondo.api.pagination import iter_items_page
from mondo.cli._column_cache import fetch_board_columns
from mondo.cli._columns import parse_settings, resolve_tag_names_to_ids
from mondo.cli._resolve import resolve_by_filters
from mondo.util.kvparse import parse_column_kv

if TYPE_CHECKING:
    from mondo.api.client import MondayClient
    from mondo.cli.context import GlobalOpts


class PositionRelative(StrEnum):
    before_at = "before_at"
    after_at = "after_at"


def split_filter_expr(expr: str) -> tuple[str, str, str]:
    """Return ``(column_id, raw_value, operator)`` for a `--filter` expression."""
    if "!=" in expr:
        col, _, raw = expr.partition("!=")
        return col.strip(), raw, "not_any_of"
    if "=" in expr:
        col, _, raw = expr.partition("=")
        return col.strip(), raw, "any_of"
    raise UsageError(f"invalid --filter {expr!r}: expected COL=VAL or COL!=VAL")


def build_filter_rule(
    parsed: tuple[str, str, str],
    column_defs: dict[str, dict[str, Any]],
    board_id: int | None = None,
) -> dict[str, Any]:
    """Build one `items_page.query_params.rule` from a parsed `(col, raw, op)`.

    Dispatches by column type so status / dropdown filters end up with the
    integer indices / option ids monday actually accepts (sending labels
    returns 0 results silently). Falls back to a raw string list when the
    column id isn't on the board (server will raise `Column not found`) or
    when the column type has no codec.
    """
    from mondo.columns import UnknownColumnTypeError, parse_filter_value

    col, raw, operator = parsed
    definition = column_defs.get(col)
    if definition is None:
        compare_value: list[Any] = [v.strip() for v in raw.split(",")]
    else:
        col_type = definition["type"]
        settings = parse_settings(definition.get("settings_str"))
        try:
            compare_value = parse_filter_value(col_type, raw, settings)
        except UnknownColumnTypeError:
            compare_value = [v.strip() for v in raw.split(",")]
        except ValueError as e:
            board_hint = f"--board {board_id} " if board_id is not None else ""
            raise UsageError(
                f"--filter {col}={raw!r}: {e}. "
                f"Run `mondo column labels {board_hint}--column {col}` "
                f"for the canonical list."
            ) from e
    return {"column_id": col, "compare_value": compare_value, "operator": operator}


def parse_columns_csv(spec: str) -> list[str]:
    """Split a `--columns col1,col2` spec; raise `UsageError` when empty."""
    col_ids = [c.strip() for c in spec.split(",") if c.strip()]
    if not col_ids:
        raise UsageError("--columns expects a comma-separated list of column ids.")
    return col_ids


def can_slim_column_values(opts: GlobalOpts) -> bool:
    """True when `--fields` provably never reads `column_values`, so the
    GraphQL query can drop it (~3x cheaper per page on big boards).

    Only `--fields` is inspected. A `-q` JMESPath cannot prove this: it
    can read fields inside predicates / sort keys yet still return whole
    rows (e.g. `[?contains(name, 'x')]`), so any `-q` — alone or combined
    with `--fields` (it runs first, against the raw rows) — keeps the
    full selection.
    """
    if opts.query is not None or not opts.fields:
        return False
    keys = [k.strip() for k in opts.fields.split(",") if k.strip()]
    return bool(keys) and all(k.split(".")[0] != "column_values" for k in keys)


def build_query_params(
    parsed_filters: list[tuple[str, str, str]] | None,
    order_by: str | None,
    column_defs: dict[str, dict[str, Any]] | None = None,
    board_id: int | None = None,
) -> dict[str, Any] | None:
    qp: dict[str, Any] = {}
    if parsed_filters:
        defs = column_defs or {}
        qp["rules"] = [build_filter_rule(f, defs, board_id=board_id) for f in parsed_filters]
        qp["operator"] = "and"
    if order_by:
        # Syntax: "column_id" or "column_id,asc" / "column_id,desc"
        col, _, direction = order_by.partition(",")
        qp["order_by"] = [{"column_id": col.strip(), "direction": (direction or "asc").strip()}]
    return qp or None


def read_batch_input(source: Path) -> list[dict[str, Any]]:
    """Read the `--batch` source and validate it's a JSON array of objects
    each carrying a `name`. Use `Path("-")` for stdin."""
    text = sys.stdin.read() if str(source) == "-" else source.read_text(encoding="utf-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise UsageError(f"--batch input is not valid JSON: {e}") from e
    if not isinstance(parsed, list):
        raise UsageError("--batch input must be a JSON array of objects.")
    if not parsed:
        raise UsageError("--batch input is an empty array — nothing to do.")
    for i, row in enumerate(parsed):
        if not isinstance(row, dict):
            raise UsageError(f"--batch row {i}: expected object, got {type(row).__name__}.")
        if not row.get("name"):
            raise UsageError(f"--batch row {i}: missing required 'name' field.")
    return parsed


def parse_column_mapping(tokens: list[str]) -> list[dict[str, Any]]:
    """Parse `source[=target]` tokens into ColumnMappingInput dicts.

    `src=dst` maps source column `src` to dest column `dst`.
    `src=` (empty target) or bare `src` drops the column on the destination
    (monday treats a null `target` as "don't carry this column over").
    """
    out: list[dict[str, Any]] = []
    for tok in tokens:
        raw = tok.strip()
        if not raw:
            continue
        if "=" in raw:
            src, _, tgt = raw.partition("=")
            src = src.strip()
            tgt = tgt.strip()
        else:
            src, tgt = raw, ""
        if not src:
            raise UsageError(
                f"--column-mapping {tok!r}: source column id is required "
                "(use 'src=dst' or 'src=' to drop)."
            )
        out.append({"source": src, "target": tgt or None})
    return out


def fetch_column_defs(
    opts: GlobalOpts,
    client: MondayClient,
    board_id: int,
    *,
    no_cache: bool = False,
    refresh: bool = False,
) -> dict[str, dict[str, Any]]:
    """One-shot fetch of `{col_id: {type, settings_str, ...}}` for a board.

    Reads from the per-board columns cache when enabled; falls back to a live
    query otherwise. Silently returns `{}` when the board isn't visible — the
    caller's codec dispatch will treat unknown columns as raw passthroughs,
    mirroring the previous behavior when the API returned no boards.
    """
    try:
        columns = fetch_board_columns(opts, client, board_id, no_cache=no_cache, refresh=refresh)
    except NotFoundError:
        return {}
    return {c["id"]: c for c in columns}


def build_column_values(
    opts: GlobalOpts,
    client: MondayClient,
    board_id: int,
    pairs: list[str],
    *,
    raw_mode: bool,
    create_labels: bool = False,
    tag_cache: dict[str, int] | None = None,
    column_defs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply codecs to `--column K=V` pairs, using live board column types.

    raw_mode=True disables codec dispatch (user's value used as-is after JSON
    parse-or-passthrough). Raw mode also skips the preflight query.

    `tag_cache` and `column_defs`, when provided, dedupe work across rows
    in a batch: a 50-row batch tagging "urgent" issues one
    `create_or_get_tag` instead of fifty, and `fetch_column_defs` runs
    once per batch instead of once per row.
    """
    from mondo.columns import UnknownColumnTypeError, parse_value

    parsed_pairs = [parse_column_kv(p) for p in pairs]

    if raw_mode:
        return dict(parsed_pairs)

    defs = column_defs if column_defs is not None else fetch_column_defs(opts, client, board_id)
    out: dict[str, Any] = {}
    for col_id, raw_value in parsed_pairs:
        definition = defs.get(col_id)
        # dict/list/None mean the user passed a structured JSON payload (or an
        # explicit "clear" signal) — honor it as raw. Bare scalars (int, float,
        # bool) are valid codec shorthand (e.g. people: `42`, numbers: `5`) and
        # must be stringified back so the codec sees them.
        if definition is None or isinstance(raw_value, (dict, list)) or raw_value is None:
            out[col_id] = raw_value
            continue
        col_type = definition["type"]
        settings = parse_settings(definition.get("settings_str"))
        str_value = raw_value if isinstance(raw_value, str) else json.dumps(raw_value)
        if col_type == "tags":
            str_value = resolve_tag_names_to_ids(client, board_id, str_value, cache=tag_cache)
        try:
            out[col_id] = parse_value(col_type, str_value, settings, create_labels=create_labels)
        except UnknownColumnTypeError:
            # Unfamiliar column type → don't translate, send raw
            out[col_id] = raw_value
        except ValueError as e:
            raise ValueError(f"--column {col_id}={raw_value!r}: {e}") from e
    return out


def build_create_variables_for_row(
    opts: GlobalOpts,
    client: MondayClient | None,
    board_id: int,
    row: dict[str, Any],
    *,
    raw_columns: bool,
    create_labels_default: bool,
    tag_cache: dict[str, int] | None = None,
    column_defs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render one batch row into the `ITEM_CREATE` variable dict.

    Reuses `build_column_values` for codec dispatch — `client` is required
    when codec preflight is needed (`raw_columns=False` and the row carries
    `columns`). Raises `ValueError` (exit 5) for malformed column values
    and `MondoError` for upstream codec failures.
    """
    raw_columns_field = row.get("columns") or []
    if not isinstance(raw_columns_field, list):
        raise ValueError(f"row {row.get('name', '?')!r}: 'columns' must be a list of K=V strings.")
    create_labels = bool(row.get("create_labels", create_labels_default))
    col_values: dict[str, Any] = {}
    if raw_columns_field:
        if raw_columns:
            col_values = dict(parse_column_kv(p) for p in raw_columns_field)
        else:
            assert client is not None, "preflight requires a client"
            col_values = build_column_values(
                opts,
                client,
                board_id,
                list(raw_columns_field),
                raw_mode=False,
                create_labels=create_labels,
                tag_cache=tag_cache,
                column_defs=column_defs,
            )
    prm = row.get("position_relative_method")
    if prm is not None:
        prm = PositionRelative(prm).value
    return {
        "board": board_id,
        "name": str(row["name"]),
        "group": row.get("group_id"),
        # monday's column_values wants a JSON-*string*, not a JSON object (§11.4).
        "values": json.dumps(col_values) if col_values else None,
        "create_labels": create_labels if create_labels else None,
        "prm": prm,
        "relto": row.get("relative_to"),
    }


def resolve_item_target(
    client: MondayClient,
    board_id: int,
    *,
    item_id: int | None,
    name_contains: str | None,
    name_matches_re: str | None,
    name_fuzzy: str | None,
    first: bool,
    fuzzy_threshold: int,
) -> int:
    """Pick a single item id for the mutation. The filter path streams
    `items_page` live and matches client-side — it deliberately skips the
    short-TTL board_items cache so name filters never resolve a mutation
    target against stale rows."""
    if item_id is not None and not (name_contains or name_matches_re or name_fuzzy):
        return item_id
    items = list(iter_items_page(client, board_id=board_id))
    chosen = resolve_by_filters(
        items,
        explicit_id=item_id,
        name_contains=name_contains,
        name_matches_re=name_matches_re,
        name_fuzzy=name_fuzzy,
        first=first,
        fuzzy_threshold=fuzzy_threshold,
        key="name",
        resource="item",
    )
    return int(chosen["id"])
