"""Skill eval pytest entry point.

Parametrised over `tests.skill_eval.tasks.tasks.ALL_TASKS`. Each task spawns
`claude -p` with the new SKILL.md + references injected via
--append-system-prompt, then a Python predicate decides pass/fail.

Gated on `claude` being on PATH (claude_binary fixture) and MONDO_TEST_BOARD_ID
(live_test_board_id fixture). Set both to run.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tests.integration._helpers import CleanupPlan
from tests.skill_eval._runner import run_skill_eval_via_claude
from tests.skill_eval.tasks.tasks import (
    ALL_TASKS,
    Task,
    TaskContext,
    smoke_check_invoke,
    workspace_id_for_eval,
)


@pytest.mark.eval
@pytest.mark.parametrize(
    "task",
    ALL_TASKS,
    ids=[t.name for t in ALL_TASKS],
)
def test_skill_task(
    task: Task,
    claude_binary: str,
    skill_corpus: dict[str, str],
    live_test_board_id: int,
    cleanup_plan: CleanupPlan,
    eval_work_dir: Path,
    eval_extra_env: dict[str, str],
) -> None:
    del claude_binary  # consumed only for the binary-on-PATH gate
    smoke_check_invoke()
    suffix = uuid.uuid4().hex[:8]
    ctx = TaskContext(
        board_id=live_test_board_id,
        workspace_id=workspace_id_for_eval(),
        suffix=suffix,
        cleanup_plan=cleanup_plan,
        extras={},
    )
    if task.setup is not None:
        task.setup(ctx)
    prompt = task.render_prompt(ctx)
    result = run_skill_eval_via_claude(
        skill_corpus=skill_corpus,
        user_prompt=prompt,
        success_predicate=lambda r: task.predicate(r, ctx),
        work_dir=eval_work_dir,
        extra_env=eval_extra_env,
        timeout_seconds=task.max_turns * 60,  # rough cap: 1 min per expected turn
    )
    if task.cleanup_register is not None:
        task.cleanup_register(result, ctx)
    if not result.success:
        pytest.fail(
            f"\nTask {task.name!r} failed predicate.\n"
            f"  prompt:        {prompt}\n"
            f"  stop_reason:   {result.stop_reason}\n"
            f"  turns:         {result.turns}\n"
            f"  duration_ms:   {result.duration_ms}\n"
            f"  cost_usd:      {result.total_cost_usd}\n"
            f"  bash_calls:    {result.bash_calls}\n"
            f"  final_text:    {result.final_text[:500]}\n"
        )
