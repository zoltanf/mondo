"""`mondo validation` — server-side validation rules (Phase 3i).

Per §14: rolling out to Pro/Enterprise (2025-04+). Violating item
creates/edits raise `RecordInvalidException`. Not supported on
multi-level subitem boards.
"""

from __future__ import annotations

import json
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.queries import (
    VALIDATION_CREATE,
    VALIDATION_DELETE,
    VALIDATION_UPDATE,
    VALIDATIONS_LIST,
)
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


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


def _dry_run(opts: GlobalOpts, query: str, variables: dict[str, Any]) -> None:
    opts.emit({"query": query, "variables": variables})
    raise typer.Exit(0)


def _confirm(opts: GlobalOpts, prompt: str) -> None:
    if opts.yes:
        return
    if not typer.confirm(prompt, default=False):
        typer.echo("aborted.")
        raise typer.Exit(1)


def _parse_json_option(raw: str | None, flag_name: str) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        typer.secho(f"error: {flag_name} is not valid JSON: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
) -> None:
    """List validation rules on a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"board": board_id}
    if opts.dry_run:
        _dry_run(opts, VALIDATIONS_LIST, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, VALIDATIONS_LIST, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    boards = data.get("boards") or []
    if not boards:
        typer.secho(f"board {board_id} not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=6)
    opts.emit(boards[0].get("validations") or [])


@app.command("create")
def create_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    column_id: str = typer.Option(..., "--column", help="Column ID the rule applies to."),
    rule_type: str = typer.Option(
        ..., "--rule-type", help="Rule type (e.g. REQUIRED, MIN_VALUE, MAX_LENGTH)."
    ),
    value: str | None = typer.Option(
        None, "--value", metavar="JSON", help="Rule value as JSON (type-dependent)."
    ),
    description: str | None = typer.Option(
        None, "--description", help="Human-readable description."
    ),
) -> None:
    """Create a validation rule on a board column."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    parsed_value = _parse_json_option(value, "--value")
    variables = {
        "board": board_id,
        "columnId": column_id,
        "ruleType": rule_type,
        "value": parsed_value,
        "description": description,
    }
    if opts.dry_run:
        _dry_run(opts, VALIDATION_CREATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, VALIDATION_CREATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("create_validation_rule") or {})


@app.command("update")
def update_cmd(
    ctx: typer.Context,
    rule_id: int = typer.Option(..., "--id", help="Validation rule ID."),
    value: str | None = typer.Option(
        None, "--value", metavar="JSON", help="New rule value as JSON."
    ),
    description: str | None = typer.Option(None, "--description", help="New description."),
) -> None:
    """Update a validation rule's value / description."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    if value is None and description is None:
        typer.secho(
            "error: pass at least one of --value or --description.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    parsed_value = _parse_json_option(value, "--value")
    variables = {"id": rule_id, "value": parsed_value, "description": description}
    if opts.dry_run:
        _dry_run(opts, VALIDATION_UPDATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, VALIDATION_UPDATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("update_validation_rule") or {})


@app.command("delete")
def delete_cmd(
    ctx: typer.Context,
    rule_id: int = typer.Option(..., "--id", help="Validation rule ID."),
) -> None:
    """Delete a validation rule."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"Delete validation rule {rule_id}?")
    variables = {"id": rule_id}
    if opts.dry_run:
        _dry_run(opts, VALIDATION_DELETE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, VALIDATION_DELETE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("delete_validation_rule") or {})
