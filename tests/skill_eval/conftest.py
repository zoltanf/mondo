"""Skill-eval fixtures.

Shells out to `claude -p` (Claude Code in headless mode), which spends against
the user's existing subscription — no Anthropic API key required.

Reuses CleanupPlan + the env shim from tests/integration/conftest.py so the
playground board stays clean after eval tasks.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import load_dotenv

from tests.integration._helpers import (
    MONDO_TEST_BOARD_ID_ENV,
    CleanupPlan,
    invoke_json,
    playground_workspace_id,
    require_live_token,
    run_cleanup,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=False)


@pytest.fixture(scope="session")
def claude_binary() -> str:
    """Resolve the `claude` binary on PATH; skip the eval suite if absent."""
    path = shutil.which("claude")
    if not path:
        pytest.skip("`claude` binary not on PATH — install Claude Code to run skill evals")
    return path


@pytest.fixture(scope="session")
def skill_corpus() -> dict[str, str]:
    """Read SKILL.md + references/*.md from the source tree (NOT the install).

    We test what we ship in this branch, not whatever is installed globally.
    """
    skill_root = Path(__file__).resolve().parents[2] / "src" / "mondo" / "skill"
    out: dict[str, str] = {"SKILL.md": (skill_root / "SKILL.md").read_text(encoding="utf-8")}
    refs_dir = skill_root / "references"
    for path in sorted(refs_dir.glob("*.md")):
        out[f"references/{path.name}"] = path.read_text(encoding="utf-8")
    return out


@pytest.fixture(scope="session")
def live_workspace_id_session() -> int:
    """Workspace id for read-only / setup paths in eval tasks. Skip if no token."""
    require_live_token()
    return playground_workspace_id()


@pytest.fixture
def live_test_board_id(live_workspace_id_session: int) -> int:
    """Board id for write-path eval tasks; skip if MONDO_TEST_BOARD_ID is missing."""
    del live_workspace_id_session
    raw = os.environ.get(MONDO_TEST_BOARD_ID_ENV)
    if not raw:
        pytest.skip(f"set {MONDO_TEST_BOARD_ID_ENV} to run write-path skill evals")
    return int(raw)


@pytest.fixture
def cleanup_plan() -> Iterator[CleanupPlan]:
    """Function-scoped LIFO cleanup plan; runs at teardown."""
    plan = CleanupPlan()
    yield plan
    run_cleanup(plan)


@pytest.fixture
def eval_work_dir(tmp_path: Path) -> Path:
    """Empty CWD for the `claude -p` subprocess. Per-test, auto-cleaned."""
    work = tmp_path / "claude_work"
    work.mkdir(parents=True, exist_ok=True)
    return work


@pytest.fixture
def eval_extra_env() -> dict[str, str]:
    """Env vars layered on top of os.environ for the `claude -p` subprocess.

    Mondo reads MONDAY_API_TOKEN; the playground token lives in MONDAY_TEST_TOKEN
    in our .env. Mirror it across so subprocess `mondo` invocations authenticate.
    """
    env: dict[str, str] = {}
    token = os.environ.get("MONDAY_TEST_TOKEN")
    if token:
        env["MONDAY_API_TOKEN"] = token
    env["MONDAY_API_VERSION"] = "2026-01"
    env["MONDO_NO_CACHE_NOTICE"] = "1"
    env["MONDO_NO_PROJECTION_WARNINGS"] = "1"
    return env


@pytest.fixture(autouse=True)
def _eval_env_shim(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mirror integration's env shim for predicates that call mondo directly via CliRunner."""
    token = os.environ.get("MONDAY_TEST_TOKEN")
    if not token:
        return
    monkeypatch.setenv("MONDAY_API_TOKEN", token)
    monkeypatch.setenv("MONDAY_API_VERSION", "2026-01")
    monkeypatch.setenv("MONDO_NO_CACHE_NOTICE", "1")
    monkeypatch.setenv("MONDO_NO_PROJECTION_WARNINGS", "1")
    monkeypatch.setenv("MONDO_HOME", str(tmp_path / "mondo_home"))
    invoke_json(["me"])
