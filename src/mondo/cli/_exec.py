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

import click
import typer

if TYPE_CHECKING:
    from mondo.api.client import MondayClient
    from mondo.cli.context import GlobalOpts


def _emit_error(exc: BaseException) -> None:
    """Print the human-readable red `error:` line plus, in machine
    output mode, the JSON envelope on stderr (Phase 5.1).

    Reads `GlobalOpts` via the active Click context — works from any
    command body. When the context isn't bound yet (rare: a failure
    raised before the root callback runs), falls back to TTY sniffing.
    """
    from mondo.cli._errors import emit_envelope, error_envelope, is_machine_output
    from mondo.cli.context import GlobalOpts

    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)

    opts: GlobalOpts | None
    try:
        ctx = click.get_current_context(silent=True)
        opts = ctx.ensure_object(GlobalOpts) if ctx is not None else None
    except RuntimeError:
        opts = None
    if is_machine_output(opts):
        emit_envelope(error_envelope(exc))


def handle_mondo_error_or_exit(exc: BaseException) -> NoReturn:
    """Standard CLI handler for any `MondoError` raised mid-command.

    Replaces the duplicated `typer.secho(f"error: {e}", ...); raise
    typer.Exit(code=int(e.exit_code))` block scattered across 60+ call
    sites. Routes through `_emit_error` so the Phase 5.1 envelope fires
    in machine-output mode.
    """
    from mondo.api.errors import MondoError

    _emit_error(exc)
    code = int(exc.exit_code) if isinstance(exc, MondoError) else 1
    raise typer.Exit(code=code) from exc


def client_or_exit(opts: GlobalOpts) -> MondayClient:
    from mondo.api.errors import MondoError

    try:
        return opts.build_client()
    except MondoError as e:
        _emit_error(e)
        raise typer.Exit(code=int(e.exit_code)) from e


def exec_or_exit(
    client: MondayClient, query: str, variables: dict[str, Any]
) -> dict[str, Any]:
    from mondo.api.errors import MondoError

    try:
        result = client.execute(query, variables=variables)
    except MondoError as e:
        _emit_error(e)
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
        _emit_error(e)
        raise typer.Exit(code=int(e.exit_code)) from e


def execute(
    opts: GlobalOpts, query: str, variables: dict[str, Any]
) -> dict[str, Any]:
    """Mutation pattern: short-circuits on `--dry-run`, else runs via
    `execute_read`."""
    if opts.dry_run:
        dry_run_and_exit(opts, query, variables)
    return execute_read(opts, query, variables)
