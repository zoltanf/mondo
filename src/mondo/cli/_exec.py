"""Shared client/exec/dry-run helpers for CLI command modules.

Every command module used to redefine the same `_client_or_exit` /
`_exec_or_exit` / `_dry_run` trio. Pulling them here gives a single place
to evolve error formatting and `MondoError`→`typer.Exit` handling.

Mutation-style callers use `execute(opts, Q, V)` (short-circuits on
`--dry-run`). The rare read-side caller that needs to run regardless of
dry-run (e.g. resolving a default workspace id before emitting the
mutation query in dry-run mode) uses `execute_read`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NoReturn

import typer

if TYPE_CHECKING:
    from mondo.api.client import MondayClient
    from mondo.cli.context import GlobalOpts


def client_or_exit(opts: GlobalOpts) -> MondayClient:
    from mondo.api.errors import MondoError

    try:
        return opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e


def exec_or_exit(
    client: MondayClient, query: str, variables: dict[str, Any]
) -> dict[str, Any]:
    from mondo.api.errors import MondoError

    try:
        result = client.execute(query, variables=variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    return result.get("data") or {}


def dry_run_and_exit(
    opts: GlobalOpts, query: str, variables: dict[str, Any]
) -> NoReturn:
    opts.emit({"query": query, "variables": variables})
    raise typer.Exit(0)


def execute_read(
    opts: GlobalOpts, query: str, variables: dict[str, Any]
) -> dict[str, Any]:
    """Build client, run the query, handle `MondoError`. No dry-run gate."""
    from mondo.api.errors import MondoError

    client = client_or_exit(opts)
    try:
        with client:
            return exec_or_exit(client, query, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e


def execute(
    opts: GlobalOpts, query: str, variables: dict[str, Any]
) -> dict[str, Any]:
    """Mutation pattern: short-circuits on `--dry-run`, else runs via
    `execute_read`."""
    if opts.dry_run:
        dry_run_and_exit(opts, query, variables)
    return execute_read(opts, query, variables)
