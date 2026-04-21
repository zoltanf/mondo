"""`mondo validation` — server-side validation rules (read-only since API 2026-01).

Monday collapsed the per-rule CRUD API: `create_validation_rule`,
`update_validation_rule`, and `delete_validation_rule` no longer exist on
the mutation root. The read-only `validations(id, type)` root query remains
and exposes `{required_column_ids, rules: JSON}`. Rule management happens
through the monday UI; this command exposes the current state for
inspection / scripting.
"""

from __future__ import annotations

import typer

from mondo.api.queries import VALIDATIONS_LIST
from mondo.cli._examples import epilog_for
from mondo.cli._exec import execute
from mondo.cli._resolve import resolve_required_id
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


def _mutation_removed() -> None:
    typer.secho(f"error: {_MUTATIONS_REMOVED_MSG}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


@app.command("list", epilog=epilog_for("validation list"))
def list_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
) -> None:
    """List validation rules on a board (required columns + rules JSON)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")
    variables = {"id": board_id}
    data = execute(opts, VALIDATIONS_LIST, variables)
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
