"""Structured-error helpers for the CLI surface (Phase 5.1).

In `-o json|jsonc|yaml` modes, every CLI error emits a JSON envelope to
stderr alongside the human-readable line. Agents that parse stderr line
by line keep working; agents that look for the JSON line can carry the
`code`, `request_id`, and `suggestion` straight into a retry decision.

Two error sources flow through here:

- `MondoError` — server-side failures classified in `mondo.api.errors`.
  Carries `request_id`, `retry_in_seconds`, and a typed `exit_code`.
- `click.exceptions.UsageError` — client-side parse errors (unknown
  flag, missing argument, bad parameter). Click's own `NoSuchOption`
  attaches `possibilities` (its difflib match against the registered
  option names); we surface those as a suggestion string.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import click
import typer

from mondo.api.errors import ExitCode, MondoError

if TYPE_CHECKING:
    from mondo.cli.context import GlobalOpts


_MACHINE_OUTPUTS: frozenset[str] = frozenset({"json", "jsonc", "yaml"})
_HUMAN_OUTPUTS: frozenset[str] = frozenset({"table", "tsv", "csv", "none"})


# Static cross-command aliases Click's difflib can't always reach (e.g.
# the user typed an old/sibling-command flag that isn't registered on
# the current command). Click's `possibilities` covers same-command
# typos via difflib already; this is the targeted fallback for things
# the agent-usability report flagged.
FLAG_ALIAS_HINTS: dict[str, list[str]] = {
    "--group-id": ["--group", "--id"],
    "--item-id": ["--item", "--id"],
    "--board-id": ["--board", "--id"],
    "--column-id": ["--column", "--id"],
    "--workspace-id": ["--workspace", "--id"],
    "--user-id": ["--user", "--id"],
    "--team-id": ["--team", "--id"],
    "--update-id": ["--update", "--id"],
    "--folder-id": ["--folder", "--id"],
    "--subitem-id": ["--subitem", "--id"],
}


def is_machine_output(opts: GlobalOpts | None) -> bool:
    """Decide whether to emit a JSON envelope alongside human errors.

    True when `--output` is one of the machine formats, OR when no
    explicit format was passed and stdout isn't a TTY (matches the
    default-format selection used by the renderer). False for explicit
    human formats. Falls back to "non-TTY" sniffing when `opts` is None
    (the failure happened before the root callback bound options).
    """
    output = (opts.output if opts is not None else None) or ""
    output = output.lower()
    if output in _MACHINE_OUTPUTS:
        return True
    if output in _HUMAN_OUTPUTS:
        return False
    return not sys.stdout.isatty()


def is_machine_output_argv(argv: list[str]) -> bool:
    """argv-based fallback for the top-level UsageError handler.

    Click parsing may fail before the Typer root callback runs, so the
    `GlobalOpts` instance may not carry `--output` yet. Scan argv
    directly for the same precedence rules as `is_machine_output`.
    """
    for i, arg in enumerate(argv):
        if arg in ("-o", "--output") and i + 1 < len(argv):
            val = argv[i + 1].lower()
            if val in _MACHINE_OUTPUTS:
                return True
            if val in _HUMAN_OUTPUTS:
                return False
        elif arg.startswith("--output="):
            val = arg.split("=", 1)[1].lower()
            if val in _MACHINE_OUTPUTS:
                return True
            if val in _HUMAN_OUTPUTS:
                return False
    return not sys.stdout.isatty()


def suggest_for_no_such_option(exc: click.exceptions.UsageError) -> str | None:
    """Build a 'did you mean ...' string for a Click UsageError.

    Pulls Click's own `possibilities` (its difflib matches against
    registered options) first, then falls back to `FLAG_ALIAS_HINTS`
    for cross-command aliases Click can't suggest.
    """
    if not isinstance(exc, click.exceptions.NoSuchOption):
        return None
    possibilities = getattr(exc, "possibilities", None) or []
    if possibilities:
        return f"did you mean {', '.join(repr(p) for p in possibilities)}?"
    hint = FLAG_ALIAS_HINTS.get(exc.option_name)
    if hint:
        return f"did you mean {', '.join(repr(h) for h in hint)}?"
    return None


def _exit_code_for(exc: BaseException) -> int:
    if isinstance(exc, MondoError):
        return int(exc.exit_code)
    if isinstance(exc, click.exceptions.UsageError):
        return int(getattr(exc, "exit_code", 2) or 2)
    return int(ExitCode.GENERIC)


def _code_for(exc: BaseException) -> str | None:
    if isinstance(exc, MondoError):
        return exc.code or type(exc).__name__
    if isinstance(exc, click.exceptions.NoSuchOption):
        return "NoSuchOption"
    if isinstance(exc, click.exceptions.MissingParameter):
        return "MissingParameter"
    if isinstance(exc, click.exceptions.BadParameter):
        return "BadParameter"
    if isinstance(exc, click.exceptions.UsageError):
        return "UsageError"
    return None


def _message_for(exc: BaseException) -> str:
    if isinstance(exc, click.exceptions.UsageError):
        # Click stores the human message on .format_message() (sometimes
        # richer than str(exc)) — use it when present.
        try:
            return exc.format_message()
        except Exception:
            return str(exc)
    return str(exc)


def error_envelope(exc: BaseException, *, suggestion: str | None = None) -> dict[str, Any]:
    """Pure factory for the stderr JSON envelope.

    Keeps the schema in one place so the `MondoError` path
    (`_exec.py`) and the `UsageError` path (`main.py`) stay in lock
    step. Drops null fields so the line is easier to parse with `jq`.
    """
    payload: dict[str, Any] = {
        "error": _message_for(exc),
        "code": _code_for(exc),
        "exit_code": _exit_code_for(exc),
    }
    if isinstance(exc, MondoError):
        payload["request_id"] = exc.request_id
        payload["retry_in_seconds"] = exc.retry_in_seconds
    if suggestion is None and isinstance(exc, click.exceptions.UsageError):
        suggestion = suggest_for_no_such_option(exc)
    if suggestion is not None:
        payload["suggestion"] = suggestion
    return {k: v for k, v in payload.items() if v is not None}


def emit_envelope(envelope: dict[str, Any]) -> None:
    """Write the envelope to stderr as a single JSON line."""
    typer.echo(json.dumps(envelope, separators=(",", ":")), err=True)
