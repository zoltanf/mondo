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

from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any, NoReturn

import click
import typer

from mondo.api.errors import MondoError, UsageError
from mondo.cli._errors import (
    emit_envelope,
    error_envelope,
    is_machine_output,
    mirror_envelope_to_stdout,
)
from mondo.cli.context import GlobalOpts as _GlobalOpts

if TYPE_CHECKING:
    from mondo.api.client import MondayClient
    from mondo.cli.context import GlobalOpts


def _emit_error(
    exc: BaseException, *, human_suffix: str | None = None, suggestion: str | None = None
) -> None:
    """Print the human-readable red `error:` line plus, in machine
    output mode, the JSON envelope on stderr (Phase 5.1).

    Reads `GlobalOpts` via the active Click context. When the context
    isn't bound yet — a failure raised before the root callback runs —
    `is_machine_output` falls back to TTY sniffing.

    `human_suffix` lets callers append a multi-line hint to the human
    output (e.g. `_execute_create_item`'s column-value reminder)
    without polluting the structured envelope. `suggestion` carries an
    actionable hint into both the human output and the structured
    `suggestion` envelope field.
    """
    line = f"error: {exc}"
    if human_suffix:
        line = f"{line}\n{human_suffix}"
    if suggestion:
        line = f"{line}\n{suggestion}"
    typer.secho(line, fg=typer.colors.RED, err=True)

    ctx = click.get_current_context(silent=True)
    opts = ctx.ensure_object(_GlobalOpts) if ctx is not None else None
    if is_machine_output(opts):
        envelope = error_envelope(exc, suggestion=suggestion)
        emit_envelope(envelope)
        mirror_envelope_to_stdout(opts, envelope)


def handle_mondo_error_or_exit(
    exc: MondoError, *, human_suffix: str | None = None, suggestion: str | None = None
) -> NoReturn:
    """Standard CLI handler for any `MondoError` raised mid-command.

    Collapses the `typer.secho(f"error: {e}", ...) + raise typer.Exit`
    pair so every command module shares one error-rendering path —
    including the Phase 5.1 JSON envelope on stderr in machine mode.

    `suggestion` surfaces an actionable hint in both the human output and
    the structured `suggestion` envelope field.
    """
    _emit_error(exc, human_suffix=human_suffix, suggestion=suggestion)
    raise typer.Exit(code=int(exc.exit_code)) from exc


def usage_error_or_exit(message: str) -> NoReturn:
    """Uniform exit for command-level usage errors.

    Wraps `message` in a `UsageError` (exit code 2) and routes it through
    the canonical `handle_mondo_error_or_exit` path: red `error:` line on
    stderr plus, in machine mode, the JSON envelope on stderr and the
    stdout mirror (#25). Replaces the bare `typer.secho(...) +
    typer.Exit(2)` pattern, which left suppressed-stderr pipelines with
    empty stdout and no clue.
    """
    handle_mondo_error_or_exit(UsageError(message))


def client_or_exit(opts: GlobalOpts) -> MondayClient:
    try:
        return opts.build_client()
    except MondoError as e:
        handle_mondo_error_or_exit(e)


def exec_or_exit(client: MondayClient, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    try:
        result = client.execute(query, variables=variables)
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    return result.get("data") or {}


def dry_run_and_exit(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> NoReturn:
    opts.emit({"query": query, "variables": variables})
    raise typer.Exit(0)


def execute_read(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Build client, run the query, handle `MondoError`. No dry-run gate."""
    client = client_or_exit(opts)
    try:
        with client:
            return exec_or_exit(client, query, variables)
    except MondoError as e:
        handle_mondo_error_or_exit(e)


def execute(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Mutation pattern: short-circuits on `--dry-run`, else runs via
    `execute_read`."""
    if opts.dry_run:
        dry_run_and_exit(opts, query, variables)
    return execute_read(opts, query, variables)


PollUntilOpt = Annotated[
    str | None,
    typer.Option(
        "--poll-until",
        metavar="JMESPATH",
        help="Re-fetch until this JMESPath expression evaluates truthy.",
        rich_help_panel="Polling",
    ),
]
PollIntervalOpt = Annotated[
    str,
    typer.Option(
        "--poll-interval",
        help="Duration between polls (e.g. 500ms, 2s, 1m). Default 2s.",
        rich_help_panel="Polling",
    ),
]
PollTimeoutOpt = Annotated[
    str,
    typer.Option(
        "--poll-timeout",
        help="Total deadline for polling (e.g. 30s, 5m). Default 60s.",
        rich_help_panel="Polling",
    ),
]


def poll_or_exit(
    fetch: Callable[[], Any],
    *,
    expression: str,
    interval: str,
    timeout: str,
) -> Any:
    """Re-call `fetch()` until `expression` is truthy against the result.

    Bridges the `--poll-until` / `--poll-interval` / `--poll-timeout` flag
    trio to `poll_until_jmespath`. Duration parse errors and bad-syntax
    JMESPath expressions surface as `error: ...` on stderr with exit 2.
    `WaitTimeoutError` is allowed to bubble so it keeps its own exit_code
    (8, TIMEOUT) via the central MondoError envelope.
    """
    from mondo.api.polling import poll_until_jmespath
    from mondo.util.duration import parse_duration

    try:
        interval_s = parse_duration(interval)
        timeout_s = parse_duration(timeout)
    except ValueError as e:
        usage_error_or_exit(str(e))
    try:
        return poll_until_jmespath(
            fetch,
            expression,
            interval_s=interval_s,
            timeout_s=timeout_s,
        )
    except ValueError as e:
        usage_error_or_exit(str(e))
