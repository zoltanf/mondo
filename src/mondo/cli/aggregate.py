"""`mondo aggregate` — board-wide aggregations (Phase 3i).

Root `aggregate(board_id, group_by, select, rules, limit)` query added in
API version 2026-01 (§14). Lets you run SUM / AVERAGE / COUNT / COUNT_DISTINCT /
MIN / MAX / MEDIAN across a board without pulling every item.

CLI accepts `--group-by` as repeatable `--group-by COL` tokens and
`--select FUNCTION:COL` tokens (e.g. `--select COUNT:*` or
`--select SUM:price`). For arbitrary filter rules, pass `--rules '<json>'`.
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


_SELECT_FUNCTIONS = {
    "SUM",
    "AVERAGE",
    "COUNT",
    "COUNT_DISTINCT",
    "MIN",
    "MAX",
    "MEDIAN",
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


def _parse_select(tokens: list[str]) -> list[dict[str, Any]]:
    """Turn `FUNCTION:COL` tokens into SelectInput dicts.

    `COUNT:*` becomes `{"function":"COUNT","column_id":null}` — monday treats
    a missing column as "all rows".
    """
    out: list[dict[str, Any]] = []
    for tok in tokens:
        if ":" not in tok:
            raise typer.BadParameter(
                f"--select {tok!r}: expected FUNCTION:COL (e.g. SUM:price, COUNT:*)."
            )
        fn, _, col = tok.partition(":")
        fn = fn.strip().upper()
        col = col.strip()
        if fn not in _SELECT_FUNCTIONS:
            raise typer.BadParameter(
                f"--select {tok!r}: unknown function {fn!r}. Valid: {sorted(_SELECT_FUNCTIONS)}."
            )
        entry: dict[str, Any] = {"function": fn}
        if col and col != "*":
            entry["column_id"] = col
        out.append(entry)
    return out


def _parse_group_by(tokens: list[str]) -> list[dict[str, Any]]:
    return [{"column_id": c.strip()} for c in tokens if c.strip()]


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
            "MEDIAN:duration). Repeatable."
        ),
    ),
    rules: str | None = typer.Option(
        None,
        "--rules",
        metavar="JSON",
        help="Arbitrary AggregateRuleInput[] as JSON.",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Max groups to return."),
) -> None:
    """Run aggregations (SUM/COUNT/AVERAGE/…) against a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    try:
        parsed_select = _parse_select(select)
        parsed_group_by = _parse_group_by(group_by or []) or None
    except typer.BadParameter as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

    parsed_rules: Any = None
    if rules is not None:
        try:
            parsed_rules = json.loads(rules)
        except json.JSONDecodeError as e:
            typer.secho(f"error: --rules is not valid JSON: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from e

    variables: dict[str, Any] = {
        "board": board_id,
        "groupBy": parsed_group_by,
        "select": parsed_select,
        "rules": parsed_rules,
        "limit": limit,
    }
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
    opts.emit(data.get("aggregate") or [])
