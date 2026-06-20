"""Session-wide pytest configuration.

This must run before any test module imports Typer. Typer computes its
``FORCE_TERMINAL`` flag at import time from ``GITHUB_ACTIONS`` /
``FORCE_COLOR`` / ``PY_COLORS`` (see ``typer.rich_utils``). When that flag is
True, Rich emits ANSI styles that fragment option flags — ``--fields`` becomes
``--`` + a styled ``fields`` span — so substring assertions like
``"--fields" in help`` fail even though the flag is present. This bites in CI:
GitHub Actions always sets ``GITHUB_ACTIONS=true``.

``_TYPER_FORCE_DISABLE_TERMINAL`` is Typer's documented switch to force plain,
color-free output. Pinning it here (at conftest import, before the CLI is
imported) makes help/error rendering deterministic regardless of the ambient
environment.
"""

from __future__ import annotations

import os

os.environ.setdefault("_TYPER_FORCE_DISABLE_TERMINAL", "1")
