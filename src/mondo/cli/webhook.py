"""`mondo webhook` — list/create/delete monday webhooks (Phase 3f).

Per monday-api.md §14:
- `create_webhook(board_id, url, event, config: JSON)` — `event` is the
  `WebhookEventType` enum (change_column_value, create_item, item_archived, …).
- monday performs a **one-time challenge handshake** against your URL when
  creating the webhook; your endpoint must echo the `challenge` JSON field.
  mondo doesn't host the server — it just posts the mutation and surfaces
  the error if the echo fails.
- `config` is optional JSON for specifically-scoped webhooks (e.g. a
  single column subscription: `{"columnId":"status"}` for
  `change_specific_column_value`).
"""

from __future__ import annotations

import json
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.queries import (
    WEBHOOK_CREATE,
    WEBHOOK_DELETE,
    WEBHOOKS_LIST,
)
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ----- helpers -----


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


# ----- commands -----


@app.command("list", epilog=epilog_for("webhook list"))
def list_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    app_only: bool = typer.Option(
        False,
        "--app-only",
        help="Restrict to webhooks created by the calling app (vs. all webhooks).",
    ),
) -> None:
    """List webhooks on a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"board": board_id, "appOnly": True if app_only else None}
    if opts.dry_run:
        _dry_run(opts, WEBHOOKS_LIST, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WEBHOOKS_LIST, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("webhooks") or [])


@app.command("create", epilog=epilog_for("webhook create"))
def create_cmd(
    ctx: typer.Context,
    board_id: int = typer.Option(..., "--board", help="Board ID."),
    url: str = typer.Option(..., "--url", help="HTTPS URL to receive webhook events."),
    event: str = typer.Option(
        ...,
        "--event",
        help=(
            "Event type (e.g. create_item, change_column_value, "
            "change_specific_column_value, item_archived). See "
            "monday-api.md §14 for the full catalog."
        ),
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        metavar="JSON",
        help=(
            "Optional JSON config for scoped webhooks "
            '(e.g. \'{"columnId":"status"}\' for change_specific_column_value).'
        ),
    ),
) -> None:
    """Create a webhook subscription.

    monday does a one-time `{"challenge":"..."}` POST to --url; your endpoint
    must echo the challenge back within the handshake window or creation
    fails (mondo surfaces the resulting error).
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    parsed_config: Any = None
    if config is not None:
        try:
            parsed_config = json.loads(config)
        except json.JSONDecodeError as e:
            typer.secho(
                f"error: --config is not valid JSON: {e}",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2) from e
    variables = {
        "board": board_id,
        "url": url,
        "event": event,
        "config": parsed_config,
    }
    if opts.dry_run:
        _dry_run(opts, WEBHOOK_CREATE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WEBHOOK_CREATE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("create_webhook") or {})


@app.command("delete", epilog=epilog_for("webhook delete"))
def delete_cmd(
    ctx: typer.Context,
    webhook_id: int = typer.Option(..., "--id", help="Webhook ID to delete."),
) -> None:
    """Delete a webhook."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    _confirm(opts, f"Delete webhook {webhook_id}?")
    variables = {"id": webhook_id}
    if opts.dry_run:
        _dry_run(opts, WEBHOOK_DELETE, variables)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, WEBHOOK_DELETE, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("delete_webhook") or {})
