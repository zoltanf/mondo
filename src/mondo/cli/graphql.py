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
from mondo.cli._exec import handle_mondo_error_or_exit, usage_error_or_exit
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

    Pass the query positionally. As a convenience, a GraphQL document
    passed to the global `-q/--query` (JMESPath projection) flag is run
    as the query — with the projection disabled, since the value can't
    be both. Pass the query positionally to combine it with a JMESPath
    projection.

    Note: `--dry-run` is not supported on this command. Raw GraphQL can't
    be safely previewed (mondo doesn't parse your query), so the flag is
    rejected rather than silently ignored.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    if opts.dry_run:
        usage_error_or_exit(
            "--dry-run is not supported with `mondo graphql`. The raw "
            "passthrough can't preview safely (mondo doesn't parse your query, "
            "and verifying success requires sending it). Review the GraphQL "
            "manually and re-run without --dry-run, or use a typed subcommand "
            "if one wraps your operation."
        )

    if query is None:
        # Issue #13: `--query '<gql>'` is the #1 agent guess (gh-api style).
        # The global `-q/--query` JMESPath flag swallows it, so when no
        # positional was given and the projection value reads as GraphQL,
        # run it as the document instead of exiting 2. The value can't be
        # both, so the JMESPath projection is disabled for this invocation.
        if opts.query and _looks_like_graphql(opts.query):
            query = opts.query
            opts.query = None
            typer.secho(
                "note: --query interpreted as the GraphQL document; pass it "
                "positionally to combine with a JMESPath projection.",
                fg=typer.colors.YELLOW,
                err=True,
            )
        else:
            usage_error_or_exit("missing required argument 'QUERY'.")

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
