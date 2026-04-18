"""`mondo graphql '<query>'` — raw GraphQL passthrough.

Reads a query (positional, from stdin via `-`, or from a file via `@path`) and
prints the parsed response envelope `{data, errors, extensions}` as JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from mondo.api.errors import MondoError
from mondo.cli.context import GlobalOpts


def _load_query(source: str) -> str:
    """Resolve a query string: inline, `-` for stdin, or `@path` for a file."""
    if source == "-":
        return sys.stdin.read()
    if source.startswith("@"):
        return Path(source[1:]).read_text()
    return source


def graphql_command(
    ctx: typer.Context,
    query: str = typer.Argument(
        ...,
        metavar="QUERY",
        help="GraphQL query/mutation. Use `-` for stdin or `@path` for a file.",
    ),
    variables: str | None = typer.Option(
        None,
        "--variables",
        "--vars",
        metavar="JSON",
        help="Variables as a JSON string. Use `@path` to read from a file.",
    ),
) -> None:
    """Send a raw GraphQL query to monday.com and print the JSON response."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    query_text = _load_query(query)
    vars_dict: dict[str, object] = {}
    if variables:
        vars_src = _load_query(variables)
        try:
            vars_dict = json.loads(vars_src)
        except json.JSONDecodeError as e:
            typer.secho(f"error: --variables is not valid JSON: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from e

    try:
        client = opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    try:
        with client:
            result = client.execute(query_text, variables=vars_dict)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    typer.echo(json.dumps(result, indent=2, sort_keys=False))
