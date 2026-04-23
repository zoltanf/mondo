"""`mondo skill` — install the bundled Claude Code skill.

Drops `SKILL.md` at `./.claude/skills/mondo/SKILL.md` (default) or
`~/.claude/skills/mondo/SKILL.md` (with `--global`), so agents running in
that directory (or globally, per user) know how to drive this CLI.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import typer

from mondo.cli._confirm import confirm_or_abort
from mondo.cli._examples import epilog_for
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("install", epilog=epilog_for("skill install"))
def install(
    ctx: typer.Context,
    global_: bool = typer.Option(
        False,
        "--global",
        "-g",
        help="Install to ~/.claude/skills/mondo/ (default: ./.claude/skills/mondo/).",
    ),
) -> None:
    """Install the mondo Claude Code skill."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    base = Path.home() / ".claude" if global_ else Path.cwd() / ".claude"
    target = base / "skills" / "mondo" / "SKILL.md"
    if target.exists():
        confirm_or_abort(opts, f"{target} already exists. Overwrite?")
    body = resources.files("mondo.skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    typer.echo(f"wrote {target}")
