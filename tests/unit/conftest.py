"""Shared fixtures for the unit suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _deterministic_cli_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """Render Typer/Rich CLI output without ANSI color in unit tests.

    CI runners (e.g. GitHub Actions) set ``FORCE_COLOR``, which makes Rich
    highlight option flags — ``--fields`` becomes
    ``\x1b[1;36m-\x1b[0m\x1b[1;36m-fields\x1b[0m`` — so substring assertions
    like ``"--fields" in help`` break even though the flag is present.
    ``NO_COLOR`` alone loses to ``FORCE_COLOR``, so drop ``FORCE_COLOR`` and
    set ``NO_COLOR`` to make help/error text deterministic regardless of the
    ambient environment.
    """
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
