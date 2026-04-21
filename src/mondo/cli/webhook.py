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

from typing import Any

import typer

from mondo.api.queries import (
    WEBHOOK_CREATE,
    WEBHOOK_DELETE,
    WEBHOOKS_LIST,
)
from mondo.cli._confirm import confirm_or_abort as _confirm
from mondo.cli._examples import epilog_for
from mondo.cli._exec import execute
from mondo.cli._json_flag import parse_json_flag
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


# ----- commands -----


@app.command("list", epilog=epilog_for("webhook list"))
def list_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
    app_only: bool = typer.Option(
        False,
        "--app-only",
        help="Restrict to webhooks created by the calling app (vs. all webhooks).",
    ),
) -> None:
    """List webhooks on a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")
    variables = {"board": board_id, "appOnly": True if app_only else None}
    data = execute(opts, WEBHOOKS_LIST, variables)
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
        parsed_config = parse_json_flag(config, flag_name="--config")
    variables = {
        "board": board_id,
        "url": url,
        "event": event,
        "config": parsed_config,
    }
    data = execute(opts, WEBHOOK_CREATE, variables)
    opts.emit(data.get("create_webhook") or {})


@app.command("delete", epilog=epilog_for("webhook delete"))
def delete_cmd(
    ctx: typer.Context,
    id_pos: int | None = typer.Argument(None, metavar="[ID]", help="Webhook ID (positional)."),
    id_flag: int | None = typer.Option(None, "--id", help="Webhook ID (flag form)."),
) -> None:
    """Delete a webhook."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    webhook_id = resolve_required_id(id_pos, id_flag, flag_name="--id", resource="webhook")
    _confirm(opts, f"Delete webhook {webhook_id}?")
    variables = {"id": webhook_id}
    data = execute(opts, WEBHOOK_DELETE, variables)
    opts.emit(data.get("delete_webhook") or {})
