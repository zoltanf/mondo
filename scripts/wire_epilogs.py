"""One-shot: add `epilog=epilog_for("<group> <cmd>")` to every @app.command.

Run from repo root: `uv run python scripts/wire_epilogs.py`. Idempotent — skips
decorators that already pass `epilog=`.

Strategy: regex over each CLI module. The group name is derived from the file
name (e.g. `board.py` → group "board", `column_doc.py` → group "column doc").
We also inject `from mondo.cli._examples import epilog_for` when missing.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI_DIR = REPO / "src" / "mondo" / "cli"

# Map module-file name → dotted command-group prefix (the example-registry key
# prefix). `None` means this file's commands register at the ROOT (no prefix).
MODULE_GROUPS: dict[str, str | None] = {
    "auth.py": "auth",
    "board.py": "board",
    "item.py": "item",
    "subitem.py": "subitem",
    "update.py": "update",
    "doc.py": "doc",
    "webhook.py": "webhook",
    "file.py": "file",
    "folder.py": "folder",
    "tag.py": "tag",
    "favorite.py": "favorite",
    "activity.py": "activity",
    "notify.py": "notify",
    "aggregate.py": "aggregate",
    "validation.py": "validation",
    "group.py": "group",
    "column.py": "column",
    # column_doc is mounted under `column` as "doc"
    "column_doc.py": "column doc",
    "workspace.py": "workspace",
    "user.py": "user",
    "team.py": "team",
    "export.py": "export",
    "import_.py": "import",
    "complexity.py": "complexity",
}

# Two shapes to rewrite:
#   @app.command("name", ...)    → name is the string literal
#   @app.command(...)            → command name = decorated func name
# The second form is harder because we need the following line's function
# definition to derive the name.
DECORATOR_NAMED_RE = re.compile(
    r"""^(?P<indent>[ \t]*)@app\.command\(\s*
        ["'](?P<cmd>[^"']+)["']
        (?P<rest>[^)]*)\)$""",
    re.MULTILINE | re.VERBOSE,
)

# Matches `@app.command()` or `@app.command(help="...", ...)` (no positional
# name arg) followed immediately by `def <fname>(...)`. Uses a lookahead.
DECORATOR_UNNAMED_RE = re.compile(
    r"""^(?P<indent>[ \t]*)@app\.command\(
        (?P<rest>(?:(?!["']).)*?)          # no positional string literal
        \)
        \n(?P=indent)def[ ]+(?P<fname>\w+)\(""",
    re.MULTILINE | re.VERBOSE | re.DOTALL,
)

IMPORT_LINE = "from mondo.cli._examples import epilog_for"


def rewrite(path: Path, group: str) -> int:
    """Rewrite one CLI module, return the number of decorators touched."""
    src = path.read_text()
    touched = 0

    def sub_named(match: re.Match[str]) -> str:
        nonlocal touched
        rest = match.group("rest")
        if "epilog=" in rest:
            return match.group(0)
        cmd = match.group("cmd")
        key = f"{group} {cmd}" if group else cmd
        indent = match.group("indent")
        new_rest = rest.rstrip()
        # Empty rest → we need a separator between the quoted name and the new
        # kwarg. Non-empty rest ending in `,` is already separated.
        sep = " " if new_rest.endswith(",") else ", "
        touched += 1
        return f'{indent}@app.command("{cmd}"{new_rest}{sep}epilog=epilog_for("{key}"))'

    def sub_unnamed(match: re.Match[str]) -> str:
        nonlocal touched
        rest = match.group("rest") or ""
        if "epilog=" in rest:
            return match.group(0)
        fname = match.group("fname")
        # Function name → command name (replace _ with - per Typer's default).
        cmd = fname.rstrip("_").replace("_", "-")
        key = f"{group} {cmd}" if group else cmd
        indent = match.group("indent")
        new_rest = rest.strip().rstrip(",")
        sep = ", " if new_rest else ""
        touched += 1
        return (
            f"{indent}@app.command({new_rest}{sep}"
            f'epilog=epilog_for("{key}"))\n{indent}def {fname}('
        )

    new_src = DECORATOR_NAMED_RE.sub(sub_named, src)
    new_src = DECORATOR_UNNAMED_RE.sub(sub_unnamed, new_src)

    if touched and IMPORT_LINE not in new_src:
        # Insert the import on the line immediately before `app = typer.Typer(`.
        # That's always at module top level, unambiguously after all imports —
        # unlike a naive "last import line" heuristic which trips on multi-line
        # parenthesized imports like `from mondo.columns import (`.
        lines = new_src.splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.startswith("app = typer.Typer"):
                lines.insert(i, IMPORT_LINE + "\n\n\n")
                break
        new_src = "".join(lines)

    if new_src != src:
        path.write_text(new_src)
    return touched


def main() -> None:
    total = 0
    for filename, group in MODULE_GROUPS.items():
        path = CLI_DIR / filename
        if not path.exists():
            print(f"  skip (missing): {filename}")
            continue
        touched = rewrite(path, group or "")
        total += touched
        print(f"  {filename:20s}  {touched} decorators wired")
    print(f"\nTotal: {total} decorators wired")


if __name__ == "__main__":
    main()
