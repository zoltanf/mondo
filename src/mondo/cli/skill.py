"""`mondo skill` — install the bundled Claude Code skill.

Drops `SKILL.md` plus the `references/*.md` drill-down pages under
`./.claude/skills/mondo/` (default) or `~/.claude/skills/mondo/`
(with `--global`), so agents running in that directory (or globally,
per user) know how to drive this CLI.
"""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import typer

from mondo.cli._confirm import confirm_or_abort
from mondo.cli._examples import epilog_for
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _iter_reference_files() -> list[tuple[str, Traversable]]:
    """Return [(filename, traversable), ...] for every *.md under references/."""
    refs_root = resources.files("mondo.skill.references")
    return sorted(
        (entry.name, entry)
        for entry in refs_root.iterdir()
        if entry.is_file() and entry.name.endswith(".md")
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
    """Install the mondo Claude Code skill (SKILL.md + reference pages)."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    base = (Path.home() if global_ else Path.cwd()) / ".claude" / "skills" / "mondo"
    skill_target = base / "SKILL.md"
    refs_dir = base / "references"

    refs = _iter_reference_files()
    targets = [skill_target] + [refs_dir / name for name, _ in refs]
    if any(t.exists() for t in targets):
        confirm_or_abort(opts, f"{base} already contains skill files. Overwrite all?")

    skill_target.parent.mkdir(parents=True, exist_ok=True)
    refs_dir.mkdir(parents=True, exist_ok=True)

    skill_body = resources.files("mondo.skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    skill_target.write_text(skill_body, encoding="utf-8")
    written = [skill_target]
    for name, trav in refs:
        dst = refs_dir / name
        dst.write_text(trav.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(dst)

    typer.echo(f"installed mondo skill to {base}")
    for path in written:
        typer.echo(f"  {path.relative_to(base.parent.parent)}")
