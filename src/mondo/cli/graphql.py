"""`mondo graphql '<query>'` — raw GraphQL passthrough.

Reads a query (positional, from stdin via `-`, or from a file via `@path`) and
emits the parsed response envelope `{data, errors, extensions}` through the
global formatter pipeline (so `-o json` / `-q` / etc. work uniformly).
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from mondo.api.errors import MondoError
from mondo.cli._exec import handle_mondo_error_or_exit
from mondo.cli._json_flag import parse_json_flag
from mondo.cli.context import GlobalOpts


def _load_query(source: str) -> str:
    """Resolve a query string: inline, `-` for stdin, or `@path` for a file."""
    if source == "-":
        return sys.stdin.read()
    if source.startswith("@"):
        return Path(source[1:]).read_text()
    return source


def _looks_like_graphql(s: str) -> bool:
    """Heuristic: does `s` look like a GraphQL document, not a JMESPath?"""
    stripped = s.lstrip()
    return stripped.startswith(("query", "mutation", "subscription", "{", "fragment"))


def graphql_command(
    ctx: typer.Context,
    query: str | None = typer.Argument(
        None,
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
    """Send a raw GraphQL query to monday.com and print the response.

    Note: `--dry-run` is not supported on this command. Raw GraphQL can't
    be safely previewed (mondo doesn't parse your query), so the flag is
    rejected rather than silently ignored.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    if opts.dry_run:
        typer.secho(
            "error: --dry-run is not supported with `mondo graphql`. The raw "
            "passthrough can't preview safely (mondo doesn't parse your query, "
            "and verifying success requires sending it). Review the GraphQL "
            "manually and re-run without --dry-run, or use a typed subcommand "
            "if one wraps your operation.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    if query is None:
        # A4/A5 in the friction report: detect when the user passed their
        # GraphQL to `-q` (global JMESPath) instead of as the positional,
        # and emit a targeted recovery hint instead of the generic
        # "Missing argument 'QUERY'" Click message.
        if opts.query and _looks_like_graphql(opts.query):
            typer.secho(
                "error: your GraphQL query was passed to `-q` (global JMESPath "
                "projection) instead of as a positional argument. Pass it "
                "positionally:\n"
                "  mondo graphql 'query { … }'",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2)
        typer.secho(
            "error: missing required argument 'QUERY'.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    query_text = _load_query(query)
    vars_dict: dict[str, object] = {}
    if variables:
        vars_dict = parse_json_flag(_load_query(variables), flag_name="--variables")

    try:
        client = opts.build_client()
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    try:
        with client:
            result = client.execute(query_text, variables=vars_dict, raw=True)
    except MondoError as e:
        handle_mondo_error_or_exit(e)

    opts.emit(result)
