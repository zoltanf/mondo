"""`mondo notify` — send monday notifications (Phase 3i).

Per monday-api.md §14:
- `create_notification(user_id, target_id, target_type, text, internal)`
- `target_type`: `Post` (for an update/reply ID) or `Project` (for item/board ID).
- Delivery is async — the returned `id` is often `-1` and NOT queryable.
- Single-user per call. Multi-user notifications need a loop (we surface
  one `--user` at a time; shell loops cover the rest).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import typer

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError
from mondo.api.queries import CREATE_NOTIFICATION
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class NotificationTargetType(StrEnum):
    Post = "Post"
    Project = "Project"


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


@app.command("send")
def send_cmd(
    ctx: typer.Context,
    user_id: int = typer.Option(..., "--user", help="Recipient user ID."),
    target_id: int = typer.Option(
        ...,
        "--target",
        help="Target ID (item / board for Project; update/reply for Post).",
    ),
    target_type: NotificationTargetType = typer.Option(
        NotificationTargetType.Project,
        "--target-type",
        help="Project (item/board) or Post (update/reply).",
        case_sensitive=True,
    ),
    text: str = typer.Option(..., "--text", help="Notification body."),
    internal: bool = typer.Option(
        False, "--internal", help="Mark as internal (monday-only, not emailed)."
    ),
) -> None:
    """Send a single notification. (monday's mutation is single-user; loop for batches.)"""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {
        "user": user_id,
        "target": target_id,
        "targetType": target_type.value,
        "text": text,
        "internal": True if internal else None,
    }
    if opts.dry_run:
        opts.emit({"query": CREATE_NOTIFICATION, "variables": variables})
        raise typer.Exit(0)
    client = _client_or_exit(opts)
    try:
        with client:
            data = _exec_or_exit(client, CREATE_NOTIFICATION, variables)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(data.get("create_notification") or {})
