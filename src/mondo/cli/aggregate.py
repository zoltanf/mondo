"""`mondo aggregate` — board-wide aggregations.

Root `aggregate(query: AggregateQueryInput!)` query (monday API 2026-01).
Lets you run SUM / AVERAGE / COUNT / MIN / MAX / MEDIAN / COUNT_DISTINCT
across a board without pulling every item.

CLI:
- `--select FUNCTION:COL` — repeatable (e.g. `COUNT:*`, `SUM:price`).
  `FUNCTION:*` is only valid for `COUNT`, which we translate to monday's
  `COUNT_ITEMS` (count of rows). For `FUNCTION:col`, we wrap the column
  as a `params` entry on the function select.
- `--group-by COL` — repeatable. The GROUP BY column is automatically
  added to the `select` list since monday rejects the query otherwise
  ("Failed to find a matching select elements for groupBy elements").
- `--filter '<json>'` — optional `ItemsQuery` to narrow the source rows.

Output shape: a list of result sets, one per group (or one total if no
`--group-by`), flattened from the raw `{results: [{entries: [...]}]}`
response into `{alias: value}` dicts for easy JMESPath / table rendering.
"""

from __future__ import annotations

import json
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.queries import AGGREGATE_BOARD
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# User-facing function names → monday's AggregateSelectFunctionName enum.
# COUNT:* is a special case handled in _build_select.
_SELECT_FN_MAP: dict[str, str] = {
    "SUM": "SUM",
    "AVERAGE": "AVERAGE",
    "COUNT": "COUNT",  # count of non-null values in a column
    "COUNT_DISTINCT": "COUNT_DISTINCT",
    "MIN": "MIN",
    "MAX": "MAX",
    "MEDIAN": "MEDIAN",
}


def _client_or_exit(opts: GlobalOpts) -> MondayClient:
    try:
        return opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e


def _exec_or_exit(client: MondayClient, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    try:
        result = client.execute(query, variables=variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    return result.get("data") or {}


def _parse_select_tokens(tokens: list[str]) -> list[tuple[str, str | None]]:
    """Parse CLI `FUNCTION:COL` tokens into (fn, col-or-None-for-wildcard) pairs."""
    out: list[tuple[str, str | None]] = []
    for tok in tokens:
        if ":" not in tok:
            raise typer.BadParameter(
                f"--select {tok!r}: expected FUNCTION:COL (e.g. SUM:price, COUNT:*)."
            )
        fn, _, col = tok.partition(":")
        fn = fn.strip().upper()
        col = col.strip()
        if fn not in _SELECT_FN_MAP:
            raise typer.BadParameter(
                f"--select {tok!r}: unknown function {fn!r}. "
                f"Valid: {sorted(_SELECT_FN_MAP)}."
            )
        if col in ("", "*"):
            if fn != "COUNT":
                raise typer.BadParameter(
                    f"--select {tok!r}: only COUNT:* (count of rows) is valid "
                    "without a column."
                )
            out.append((fn, None))
        else:
            out.append((fn, col))
    return out


def _build_select_elements(
    parsed: list[tuple[str, str | None]],
    group_by: list[str],
) -> list[dict[str, Any]]:
    """Construct the `select` list for AggregateQueryInput.

    Each group_by column MUST appear in select (monday rejects the query
    otherwise). Function selects wrap their column as a nested COLUMN param.
    """
    elements: list[dict[str, Any]] = []

    # Group-by columns must each have a matching COLUMN select.
    for gb_col in group_by:
        elements.append(
            {
                "type": "COLUMN",
                "column": {"column_id": gb_col},
                "as": gb_col,
            }
        )

    # Function selects. COUNT:* → COUNT_ITEMS (no params). Others take the
    # column as a nested COLUMN param.
    for fn, col in parsed:
        if col is None:
            # COUNT:* — count of all rows (items on the table)
            elements.append(
                {
                    "type": "FUNCTION",
                    "function": {"function": "COUNT_ITEMS", "params": []},
                    "as": "count",
                }
            )
        else:
            elements.append(
                {
                    "type": "FUNCTION",
                    "function": {
                        "function": _SELECT_FN_MAP[fn],
                        "params": [
                            {
                                "type": "COLUMN",
                                "column": {"column_id": col},
                                "as": f"_{col}",
                            }
                        ],
                    },
                    "as": f"{fn.lower()}_{col}",
                }
            )

    return elements


def _flatten_entry_value(value: dict[str, Any] | None) -> Any:
    """Reduce the AggregateResult union to a primitive."""
    if not isinstance(value, dict):
        return value
    # AggregateBasicAggregationResult
    if "result" in value and value.get("__typename") == "AggregateBasicAggregationResult":
        return value.get("result")
    # AggregateGroupByResult — prefer the typed variant, fall back to generic `value`.
    for k in ("value_string", "value_int", "value_float", "value_boolean"):
        if value.get(k) is not None:
            return value[k]
    return value.get("value")


def _flatten_results(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn the nested aggregate response into a list of {alias: value} dicts."""
    agg = response.get("aggregate") or {}
    result_sets = agg.get("results") or []
    flattened: list[dict[str, Any]] = []
    for rs in result_sets:
        entries = rs.get("entries") or []
        flattened.append({e.get("alias"): _flatten_entry_value(e.get("value")) for e in entries})
    return flattened


@app.command("board")
def board_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    group_by: list[str] | None = typer.Option(
        None,
        "--group-by",
        help="Column ID to group by (repeatable). Omit for a single aggregate row.",
    ),
    select: list[str] = typer.Option(
        ...,
        "--select",
        help=(
            "Aggregation spec as FUNCTION:COL (e.g. SUM:price, COUNT:*, "
            "MEDIAN:duration). Repeatable. COUNT:* counts all rows on the board."
        ),
    ),
    filter_query: str | None = typer.Option(
        None,
        "--filter",
        metavar="JSON",
        help="Optional ItemsQuery JSON to narrow the source rows.",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Max result sets to return."),
) -> None:
    """Run aggregations (SUM/COUNT/AVERAGE/…) against a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    try:
        parsed_select = _parse_select_tokens(select)
    except typer.BadParameter as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

    group_by_cols = [c.strip() for c in (group_by or []) if c.strip()]

    parsed_filter: Any = None
    if filter_query is not None:
        try:
            parsed_filter = json.loads(filter_query)
        except json.JSONDecodeError as e:
            typer.secho(f"error: --filter is not valid JSON: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from e

    agg_input: dict[str, Any] = {
        "from": {"type": "TABLE", "id": str(board_id)},
        "select": _build_select_elements(parsed_select, group_by_cols),
    }
    if group_by_cols:
        agg_input["group_by"] = [{"column_id": c} for c in group_by_cols]
    if parsed_filter is not None:
        agg_input["query"] = parsed_filter
    if limit is not None:
        agg_input["limit"] = limit

    variables = {"q": agg_input}
    if opts.dry_run:
        opts.emit({"query": AGGREGATE_BOARD, "variables": variables})
        raise typer.Exit(0)

    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, AGGREGATE_BOARD, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit(_flatten_results(data))
