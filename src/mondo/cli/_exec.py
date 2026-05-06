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

from mondo.api.errors import MondoError
from mondo.cli._errors import emit_envelope, error_envelope, is_machine_output
from mondo.cli.context import GlobalOpts as _GlobalOpts

if TYPE_CHECKING:
    from mondo.api.client import MondayClient
    from mondo.cli.context import GlobalOpts


def _emit_error(exc: BaseException, *, human_suffix: str | None = None) -> None:
    """Print the human-readable red `error:` line plus, in machine
    output mode, the JSON envelope on stderr (Phase 5.1).

    Reads `GlobalOpts` via the active Click context. When the context
    isn't bound yet — a failure raised before the root callback runs —
    `is_machine_output` falls back to TTY sniffing.

    `human_suffix` lets callers append a multi-line hint to the human
    output (e.g. `_execute_create_item`'s column-value reminder)
    without polluting the structured envelope.
    """
    line = f"error: {exc}"
    if human_suffix:
        line = f"{line}\n{human_suffix}"
    typer.secho(line, fg=typer.colors.RED, err=True)

    ctx = click.get_current_context(silent=True)
    opts = ctx.ensure_object(_GlobalOpts) if ctx is not None else None
    if is_machine_output(opts):
        emit_envelope(error_envelope(exc))


def handle_mondo_error_or_exit(
    exc: MondoError, *, human_suffix: str | None = None
) -> NoReturn:
    """Standard CLI handler for any `MondoError` raised mid-command.

    Collapses the `typer.secho(f"error: {e}", ...) + raise typer.Exit`
    pair so every command module shares one error-rendering path —
    including the Phase 5.1 JSON envelope on stderr in machine mode.
    """
    _emit_error(exc, human_suffix=human_suffix)
    raise typer.Exit(code=int(exc.exit_code)) from exc


def client_or_exit(opts: GlobalOpts) -> MondayClient:
    try:
        return opts.build_client()
    except MondoError as e:
        handle_mondo_error_or_exit(e)


def exec_or_exit(
    client: MondayClient, query: str, variables: dict[str, Any]
) -> dict[str, Any]:
    try:
        result = client.execute(query, variables=variables)
    except MondoError as e:
        handle_mondo_error_or_exit(e)
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
    client = client_or_exit(opts)
    try:
        with client:
            return exec_or_exit(client, query, variables)
    except MondoError as e:
        handle_mondo_error_or_exit(e)


def execute(
    opts: GlobalOpts, query: str, variables: dict[str, Any]
) -> dict[str, Any]:
    """Mutation pattern: short-circuits on `--dry-run`, else runs via
    `execute_read`."""
    if opts.dry_run:
        dry_run_and_exit(opts, query, variables)
    return execute_read(opts, query, variables)
