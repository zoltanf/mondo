"""Shared helpers for the live integration suite.

Extracted from `test_live_writes.py` so multiple feature-specific test
modules can share the CLI invocation, JSON parsing, polling, and LIFO
cleanup primitives without duplication.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import pytest
from typer.testing import CliRunner

from mondo.cli.main import app

MONDAY_TEST_TOKEN_ENV = "MONDAY_TEST_TOKEN"
MONDAY_TEST_WORKSPACE_ID_ENV = "MONDAY_TEST_WORKSPACE_ID"
MONDO_TEST_WORKSPACE_ID_ENV = "MONDO_TEST_WORKSPACE_ID"
MONDO_TEST_BOARD_ID_ENV = "MONDO_TEST_BOARD_ID"
MONDO_TEST_DOC_ID_ENV = "MONDO_TEST_DOC_ID"
DEFAULT_PLAYGROUND_WORKSPACE_ID = 592446
API_VERSION = "2026-01"

runner = CliRunner()


def require_live_token() -> str:
    token = os.environ.get(MONDAY_TEST_TOKEN_ENV)
    if not token:
        pytest.skip(f"set {MONDAY_TEST_TOKEN_ENV} to run live Monday integration tests")
    return token


def playground_workspace_id() -> int:
    raw = (
        os.environ.get(MONDAY_TEST_WORKSPACE_ID_ENV)
        or os.environ.get(MONDO_TEST_WORKSPACE_ID_ENV)
    )
    return int(raw) if raw else DEFAULT_PLAYGROUND_WORKSPACE_ID


def format_failure(args: list[str], result: Any) -> str:
    return (
        f"mondo {' '.join(args)}\n"
        f"exit_code={result.exit_code}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def invoke(
    args: list[str],
    *,
    expect_exit: int | None = 0,
    input: str | None = None,
) -> Any:
    """Run `mondo <args>` through Typer's CliRunner.

    Always passes `--yes --output json`. If `expect_exit` is not None,
    asserts the exit code matches.
    """
    result = runner.invoke(app, ["--yes", "--output", "json", *args], input=input)
    if expect_exit is not None:
        assert result.exit_code == expect_exit, format_failure(args, result)
    return result


def json_output(result: Any) -> Any:
    text = result.stdout.strip()
    assert text, "command produced no JSON output"
    return json.loads(text)


def invoke_json(
    args: list[str],
    *,
    expect_exit: int | None = 0,
    input: str | None = None,
) -> Any:
    return json_output(invoke(args, expect_exit=expect_exit, input=input))


def wait_for(
    description: str,
    probe: Any,
    *,
    timeout_seconds: float = 45.0,
    interval_seconds: float = 1.0,
) -> Any:
    """Poll `probe()` until it stops raising AssertionError or the deadline passes."""
    deadline = time.monotonic() + timeout_seconds
    last_error: AssertionError | None = None
    while time.monotonic() < deadline:
        try:
            return probe()
        except AssertionError as exc:
            last_error = exc
            time.sleep(interval_seconds)
    detail = f": {last_error}" if last_error else ""
    raise AssertionError(f"timed out waiting for {description}{detail}")


@dataclass
class CleanupAction:
    label: str
    args: list[str]


@dataclass
class CleanupPlan:
    """LIFO cleanup queue for live tests.

    Tests register cleanup actions with `add(label, *cli_args)`. The
    surrounding fixture runs them in reverse order at teardown, retrying
    each for 45s with 1s interval and accepting exit codes {0, 6}
    (success or already-deleted).
    """

    actions: list[CleanupAction] = field(default_factory=list)

    def add(self, label: str, *args: str) -> None:
        self.actions.append(CleanupAction(label=label, args=list(args)))


def run_cleanup(plan: CleanupPlan) -> None:
    """Execute a cleanup plan LIFO, retry-until-deadline per action.

    Collects failures and raises pytest.fail at the end if any failed.
    Used by both function-scoped and session-scoped cleanup fixtures.
    """
    failures: list[str] = []
    for action in reversed(plan.actions):
        deadline = time.monotonic() + 45.0
        while True:
            result = invoke(action.args, expect_exit=None)
            if result.exit_code in {0, 6}:
                break
            if time.monotonic() >= deadline:
                failures.append(
                    f"{action.label} cleanup failed\n{format_failure(action.args, result)}"
                )
                break
            time.sleep(1.0)
    if failures:
        pytest.fail("\n\n".join(failures))


def extract_id(payload: Any) -> str:
    """Pull `id` out of a CLI JSON payload, normalising to str."""
    if isinstance(payload, dict) and "id" in payload:
        return str(payload["id"])
    raise AssertionError(f"no 'id' in payload: {payload!r}")
