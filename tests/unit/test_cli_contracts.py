"""Cross-command contract tests.

These don't test a specific feature — they assert invariants across the whole
CLI so new commands inherit the same guarantees without per-command test drift:

- Any command accepting `--format markdown` must emit raw markdown to stdout,
  not a JSON-encoded string. Driven by walking the Click tree so a new such
  command that isn't registered here fails the sanity check.
- Only `src/mondo/cli/_confirm.py` may call `typer.confirm(...)` directly; all
  other destructive commands must go through the shared helper so the non-TTY
  `--yes` hint stays consistent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import click
import pytest
import typer.main as _typer_main
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


# ---------------------------------------------------------------------------
# Tree walking helpers
# ---------------------------------------------------------------------------


def _walk(cmd: click.Command, path: list[str]):
    yield path, cmd
    if isinstance(cmd, click.Group):
        ctx = click.Context(cmd)
        for child_name in cmd.list_commands(ctx):
            child = cmd.get_command(ctx, child_name)
            if child is not None:
                yield from _walk(child, [*path, child_name])


def _root_click_app() -> click.Command:
    return _typer_main.get_command(app)


def _commands_with_format_choice(choice: str) -> set[str]:
    """Paths (without the leading "mondo") of commands whose `--format` Choice contains `choice`."""
    found: set[str] = set()
    for path, cmd in _walk(_root_click_app(), ["mondo"]):
        for param in getattr(cmd, "params", []):
            opts = list(getattr(param, "opts", []) or [])
            if "--format" not in opts:
                continue
            ptype = getattr(param, "type", None)
            if isinstance(ptype, click.Choice) and choice in ptype.choices:
                found.add(" ".join(path[1:]))
    return found


# ---------------------------------------------------------------------------
# Contract 1 — `--format markdown` must emit raw markdown
# ---------------------------------------------------------------------------


def _column_doc_get_mocks(httpx_mock: HTTPXMock) -> None:
    column_value = json.dumps(
        {
            "files": [
                {
                    "linkToFile": "https://x/docs/5000",
                    "fileType": "MONDAY_DOC",
                    "docId": 700,
                    "objectId": 5000,
                }
            ]
        }
    )
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json=_ok(
            {
                "items": [
                    {
                        "id": "1",
                        "name": "Spec item",
                        "board": {
                            "id": "42",
                            "columns": [
                                {
                                    "id": "spec",
                                    "title": "Spec",
                                    "type": "doc",
                                    "settings_str": "{}",
                                }
                            ],
                        },
                        "column_values": [
                            {"id": "spec", "type": "doc", "text": "", "value": column_value}
                        ],
                    }
                ]
            }
        ),
    )
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json=_ok(
            {
                "docs": [
                    {
                        "id": "700",
                        "object_id": 5000,
                        "blocks": [
                            {
                                "type": "heading",
                                "content": {"deltaFormat": [{"insert": "Spec"}]},
                            },
                            {
                                "type": "normal_text",
                                "content": {"deltaFormat": [{"insert": "Body line"}]},
                            },
                        ],
                    }
                ]
            }
        ),
    )


def _doc_get_mocks(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=ENDPOINT,
        method="POST",
        json=_ok(
            {
                "docs": [
                    {
                        "id": "7",
                        "blocks": [
                            {
                                "id": "b1",
                                "type": "normal_text",
                                "content": {"deltaFormat": [{"insert": "Body line"}]},
                            }
                        ],
                    }
                ]
            }
        ),
    )


# Keyed by the argv path (no leading "mondo"). Each entry provides:
#   args: required argv to reach the markdown-emitting code path.
#   setup: installs the HTTP mocks the command will make.
# Sanity check below ensures this dict stays in sync with the CLI tree.
_MARKDOWN_CASES: dict[str, dict] = {
    "column doc get": {
        "args": ["--item", "1", "--column", "spec"],
        "setup": _column_doc_get_mocks,
    },
    "doc get": {
        "args": ["--id", "7"],
        "setup": _doc_get_mocks,
    },
}


def test_markdown_commands_registered_in_contract_table() -> None:
    """Every `--format markdown` command in the tree must have a contract entry.

    If this fails, a new markdown-emitting command was added (or an existing one
    renamed) — register it in `_MARKDOWN_CASES` with its mocks so the raw-output
    assertion runs against it too.
    """
    discovered = _commands_with_format_choice("markdown")
    registered = set(_MARKDOWN_CASES)
    assert discovered == registered, (
        f"Commands with --format markdown on the CLI tree: {sorted(discovered)}\n"
        f"Cases registered in _MARKDOWN_CASES: {sorted(registered)}\n"
        "Update _MARKDOWN_CASES so it matches the tree."
    )


@pytest.mark.parametrize("command_path", sorted(_MARKDOWN_CASES))
def test_markdown_output_is_raw_not_json_quoted(
    command_path: str, httpx_mock: HTTPXMock
) -> None:
    """Contract: `--format markdown` writes raw text, never a JSON-encoded string.

    Catches the bug shape where `opts.emit(markdown_str)` round-trips the string
    through `json.dumps`, producing `"# Heading\\n..."` instead of real markdown.
    """
    case = _MARKDOWN_CASES[command_path]
    case["setup"](httpx_mock)
    argv = command_path.split() + case["args"] + ["--format", "markdown"]
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.stdout

    stripped = result.stdout.lstrip()
    assert not stripped.startswith('"'), (
        f"{command_path}: markdown output starts with a JSON quote — "
        f"likely routed through opts.emit() instead of typer.echo().\n"
        f"stdout: {result.stdout!r}"
    )
    assert "\\n" not in result.stdout, (
        f"{command_path}: markdown output contains escaped newlines — "
        f"likely JSON-encoded.\nstdout: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Contract 2 — no inline `typer.confirm(...)` outside the shared helper
# ---------------------------------------------------------------------------


_CLI_DIR = Path(__file__).resolve().parents[2] / "src" / "mondo" / "cli"
_INLINE_CONFIRM_RE = re.compile(r"\btyper\.confirm\s*\(")


def test_no_inline_typer_confirm_outside_shared_helper() -> None:
    """Only `_confirm.py` may call `typer.confirm(...)` directly.

    Every destructive command must go through `confirm_or_abort` from
    `mondo.cli._confirm` so the non-TTY `--yes` hint and any future shared
    policy land consistently. If this fails, replace the inline call with:

        from mondo.cli._confirm import confirm_or_abort as _confirm
        _confirm(opts, "Really?")
    """
    offenders: list[str] = []
    for py in sorted(_CLI_DIR.glob("*.py")):
        if py.name == "_confirm.py":
            continue
        for lineno, line in enumerate(py.read_text().splitlines(), start=1):
            if _INLINE_CONFIRM_RE.search(line):
                offenders.append(f"{py.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Found inline typer.confirm(...) calls outside _confirm.py:\n"
        + "\n".join(offenders)
        + "\n\nUse `from mondo.cli._confirm import confirm_or_abort` instead."
    )
