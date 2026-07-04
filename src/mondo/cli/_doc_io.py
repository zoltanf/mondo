"""Input loaders for `mondo doc` write commands.

Small helpers that resolve the `--markdown`/`--html` XOR `--from-file` XOR
`--from-stdin` input triple into a single string, or exit with a usage error.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mondo.cli._exec import usage_error_or_exit


def _load_markdown(inline: str | None, path: Path | None, from_stdin: bool) -> str:
    sources = sum(x is not None and x is not False for x in (inline, path, from_stdin))
    if sources == 0:
        usage_error_or_exit("provide --markdown, --from-file @path, or --from-stdin")
    if sources > 1:
        usage_error_or_exit("--markdown, --from-file, and --from-stdin are mutually exclusive")
    if path is not None:
        return path.read_text()
    if from_stdin:
        return sys.stdin.read()
    assert inline is not None
    return inline


def _load_html(inline: str | None, path: Path | None, from_stdin: bool) -> str:
    sources = sum(x is not None and x is not False for x in (inline, path, from_stdin))
    if sources == 0:
        usage_error_or_exit("provide --html, --from-file @path, or --from-stdin")
    if sources > 1:
        usage_error_or_exit("--html, --from-file, and --from-stdin are mutually exclusive")
    if path is not None:
        return path.read_text()
    if from_stdin:
        return sys.stdin.read()
    assert inline is not None
    return inline
