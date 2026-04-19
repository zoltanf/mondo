"""`mondo validation` — server-side validation rules (read-only since API 2026-01).

Monday collapsed the per-rule CRUD API: `create_validation_rule`,
`update_validation_rule`, and `delete_validation_rule` no longer exist on
the mutation root. The read-only `validations(id, type)` root query remains
and exposes `{required_column_ids, rules: JSON}`. Rule management happens
through the monday UI; this command exposes the current state for
inspection / scripting.
"""

from __future__ import annotations

from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.queries import VALIDATIONS_LIST
from mondo.cli._examples import epilog_for
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


_MUTATIONS_REMOVED_MSG = (
    "monday removed the validation-rule CRUD mutations in API 2026-01; "
    "rule management is UI-only now. `mondo validation list` still works "
    "and returns the current rule set for a board."
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


def _mutation_removed() -> None:
    typer.secho(f"error: {_MUTATIONS_REMOVED_MSG}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


@app.command("list", epilog=epilog_for("validation list"))
def list_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
) -> None:
    """List validation rules on a board (required columns + rules JSON)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"id": board_id}
    if opts.dry_run:
        _dry_run(opts, VALIDATIONS_LIST, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, VALIDATIONS_LIST, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("validations") or {})


@app.command("create", epilog=epilog_for("validation create"))
def create_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    column_id: str = typer.Option(..., "--column", help="Column ID the rule applies to."),
    rule_type: str = typer.Option(..., "--rule-type", help="Rule type."),
    value: str | None = typer.Option(None, "--value", metavar="JSON"),
    description: str | None = typer.Option(None, "--description"),
) -> None:
    """Create a validation rule. REMOVED from monday's 2026-01 schema."""
    _mutation_removed()


@app.command("update", epilog=epilog_for("validation update"))
def update_cmd(
    ctx: typer.Context,
    rule_id: int = typer.Option(..., "--id", help="Validation rule ID."),
    value: str | None = typer.Option(None, "--value", metavar="JSON"),
    description: str | None = typer.Option(None, "--description"),
) -> None:
    """Update a validation rule. REMOVED from monday's 2026-01 schema."""
    _mutation_removed()


@app.command("delete", epilog=epilog_for("validation delete"))
def delete_cmd(
    ctx: typer.Context,
    rule_id: int = typer.Option(..., "--id", help="Validation rule ID."),
) -> None:
    """Delete a validation rule. REMOVED from monday's 2026-01 schema."""
    _mutation_removed()
