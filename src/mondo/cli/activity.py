"""`mondo activity` — read monday activity logs (Phase 3h).

Activity logs are nested only — no root `activity_logs` query. The CLI
walks `boards(ids:).activity_logs(...)` with page-based pagination and
surfaces the raw log records. `data` is a JSON-encoded string per §14.

Retention: ~1 week on non-Enterprise; longer on Enterprise.
"""

from __future__ import annotations

from typing import Any

import typer

from mondo.api.errors import MondoError
from mondo.api.queries import BOARD_ACTIVITY_LOGS
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit, exec_or_exit
from mondo.cli._resolve import resolve_required_id
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("board", epilog=epilog_for("activity board"))
def board_cmd(
    ctx: typer.Context,
    board_pos: int | None = typer.Argument(
        None, metavar="[BOARD_ID]", help="Board ID (positional)."
    ),
    board_flag: int | None = typer.Option(None, "--board", help="Board ID (flag form)."),
    since: str | None = typer.Option(
        None, "--since", help="Lower bound ISO-8601 timestamp (inclusive)."
    ),
    until: str | None = typer.Option(
        None, "--until", help="Upper bound ISO-8601 timestamp (inclusive)."
    ),
    user: list[int] | None = typer.Option(None, "--user", help="Filter by user ID (repeatable)."),
    item: list[int] | None = typer.Option(None, "--item", help="Filter by item ID (repeatable)."),
    group: list[str] | None = typer.Option(
        None, "--group", help="Filter by group ID (repeatable)."
    ),
    column: list[str] | None = typer.Option(
        None, "--column", help="Filter by column ID (repeatable)."
    ),
    limit: int = typer.Option(100, "--limit", help="Page size (max 100)."),
    max_items: int | None = typer.Option(
        None, "--max-items", help="Stop after this many log entries total."
    ),
) -> None:
    """Stream activity log entries for a board."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    board_id = resolve_required_id(board_pos, board_flag, flag_name="--board", resource="board")

    base_vars: dict[str, Any] = {
        "board": board_id,
        "userIds": user or None,
        "columnIds": column or None,
        "groupIds": group or None,
        "itemIds": item or None,
        "fromDate": since,
        "toDate": until,
    }

    if opts.dry_run:
        opts.emit(
            {
                "query": "<activity_logs page iterator>",
                "variables": {**base_vars, "limit": limit, "max_items": max_items},
            }
        )
        raise typer.Exit(0)

    client = client_or_exit(opts)
    collected: list[dict[str, Any]] = []
    page = 1
    try:
        with client:
            while True:
                data = exec_or_exit(
                    client,
                    BOARD_ACTIVITY_LOGS,
                    {**base_vars, "limit": limit, "page": page},
                )
                boards = data.get("boards") or []
                if not boards:
                    if page == 1:
                        typer.secho(
                            f"board {board_id} not found.",
                            fg=typer.colors.RED,
                            err=True,
                        )
                        raise typer.Exit(code=6)
                    break
                logs = boards[0].get("activity_logs") or []
                if not logs:
                    break
                for log in logs:
                    if max_items is not None and len(collected) >= max_items:
                        break
                    collected.append(log)
                if max_items is not None and len(collected) >= max_items:
                    break
                if len(logs) < limit:
                    break
                page += 1
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(collected)
