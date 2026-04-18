"""`mondo complexity status` — fire a trivial query and report the live budget.

Each CLI invocation is a fresh process with a fresh `ComplexityMeter`, so
`status` issues a `query { me { id } }` (with the usual injected
`complexity { ... }` block) and prints what monday just told us about our
remaining per-minute budget.
"""

from __future__ import annotations

import typer

from mondo.api.errors import MondoError
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


_PROBE_QUERY = "query { me { id } }"


@app.command("status")
def status_cmd(ctx: typer.Context) -> None:
    """Print the current monday complexity budget (fires one cheap query)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    try:
        client = opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    try:
        with client:
            client.execute(_PROBE_QUERY)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit(client.meter.to_dict())
