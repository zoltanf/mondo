"""Canned eval tasks for the skill_eval suite.

Each Task pairs a user prompt with a Python predicate that inspects the
EvalResult (transcript + bash calls + final text) and decides pass/fail.
Predicates may also call back into mondo via `tests.integration._helpers.invoke_json`
to verify side-effects on the playground board.

Per-task `setup` runs before the agent loop; `cleanup_register` runs after, taking
the EvalResult so it can extract created ids and queue them for LIFO teardown.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tests.integration._helpers import (
    CleanupPlan,
    invoke,
    invoke_json,
    playground_workspace_id,
)

if TYPE_CHECKING:
    from tests.skill_eval._runner import EvalResult


@dataclass(frozen=True)
class TaskContext:
    board_id: int
    workspace_id: int
    suffix: str
    cleanup_plan: CleanupPlan
    extras: dict[str, Any]


@dataclass(frozen=True)
class Task:
    name: str
    prompt_template: str
    predicate: Callable[["EvalResult", TaskContext], bool]
    max_turns: int = 8
    setup: Callable[[TaskContext], None] | None = None
    cleanup_register: Callable[["EvalResult", TaskContext], None] | None = None

    def render_prompt(self, ctx: TaskContext) -> str:
        return self.prompt_template.format(
            board_id=ctx.board_id,
            workspace_id=ctx.workspace_id,
            **ctx.extras,
        )


# --- Task 1: read-only board listing ----------------------------------------


def _t1_predicate(result: "EvalResult", ctx: TaskContext) -> bool:
    del ctx
    if not any(
        re.search(r"\bmondo\s+board\s+list\b", c) and "--workspace" in c
        for c in result.bash_calls
    ):
        return False
    return bool(result.final_text and result.final_text.strip())


task_list_boards = Task(
    name="read_only_board_list",
    prompt_template=(
        "List the active boards in workspace {workspace_id}. Just give me names "
        "and ids — no need to show every column."
    ),
    predicate=_t1_predicate,
    max_turns=4,
)


# --- Task 2: create a group --------------------------------------------------


def _t2_setup(ctx: TaskContext) -> None:
    ctx.extras["target_group_title"] = f"Q3 Goals {ctx.suffix}"


def _t2_predicate(result: "EvalResult", ctx: TaskContext) -> bool:
    del result
    target = ctx.extras["target_group_title"]
    groups = invoke_json(["group", "list", "--board", str(ctx.board_id)])
    return any(g.get("title") == target for g in groups)


def _t2_cleanup(result: "EvalResult", ctx: TaskContext) -> None:
    del result
    target = ctx.extras["target_group_title"]
    groups = invoke_json(["group", "list", "--board", str(ctx.board_id)])
    for group in groups:
        if group.get("title") == target:
            ctx.cleanup_plan.add(
                f"eval group {group['id']}",
                "group", "delete",
                "--board", str(ctx.board_id),
                "--id", group["id"],
                "--hard",
            )


task_create_group = Task(
    name="create_group",
    prompt_template=(
        "On board {board_id}, create a new group called \"{target_group_title}\"."
    ),
    setup=_t2_setup,
    predicate=_t2_predicate,
    cleanup_register=_t2_cleanup,
    max_turns=4,
)


# --- Task 3: set status of an item ------------------------------------------


def _t3_setup(ctx: TaskContext) -> None:
    groups = invoke_json(["group", "list", "--board", str(ctx.board_id)])
    if not groups:
        raise RuntimeError("test board has no groups")
    columns = invoke_json(["column", "list", "--board", str(ctx.board_id)])
    status_col = next((c for c in columns if c.get("type") == "status"), None)
    if status_col is None:
        # Create a status column with a stable id for the eval.
        created = invoke_json(
            [
                "column", "create",
                "--board", str(ctx.board_id),
                "--title", f"E2E Eval Status {ctx.suffix}",
                "--type", "status",
                "--id", f"eval_status_{ctx.suffix.lower()}",
            ]
        )
        ctx.cleanup_plan.add(
            f"eval status col {created['id']}",
            "column", "delete",
            "--board", str(ctx.board_id),
            "--column", created["id"],
        )
        ctx.extras["status_col_id"] = created["id"]
    else:
        ctx.extras["status_col_id"] = status_col["id"]

    item = invoke_json(
        [
            "item", "create",
            "--board", str(ctx.board_id),
            "--group", groups[0]["id"],
            "--name", f"E2E Eval Status Item {ctx.suffix}",
        ]
    )
    item_id = int(item["id"])
    ctx.cleanup_plan.add(
        f"eval status item {item_id}",
        "item", "delete", "--id", str(item_id), "--hard",
    )
    ctx.extras["item_id"] = item_id


def _t3_predicate(result: "EvalResult", ctx: TaskContext) -> bool:
    del result
    item_id = ctx.extras["item_id"]
    col_id = ctx.extras["status_col_id"]
    rendered = invoke_json(["column", "get", "--item", str(item_id), "--column", col_id])
    return isinstance(rendered, str) and rendered.lower() == "done"


task_set_status = Task(
    name="set_status_done",
    prompt_template=(
        "Mark item {item_id} as Done. The status column id is {status_col_id}."
    ),
    setup=_t3_setup,
    predicate=_t3_predicate,
    max_turns=4,
)


# --- Task 4: post an update --------------------------------------------------


def _t4_setup(ctx: TaskContext) -> None:
    groups = invoke_json(["group", "list", "--board", str(ctx.board_id)])
    item = invoke_json(
        [
            "item", "create",
            "--board", str(ctx.board_id),
            "--group", groups[0]["id"],
            "--name", f"E2E Eval Update Item {ctx.suffix}",
        ]
    )
    item_id = int(item["id"])
    ctx.cleanup_plan.add(
        f"eval update item {item_id}",
        "item", "delete", "--id", str(item_id), "--hard",
    )
    ctx.extras["item_id"] = item_id
    ctx.extras["update_marker"] = f"reviewed-{ctx.suffix}"


def _t4_predicate(result: "EvalResult", ctx: TaskContext) -> bool:
    del result
    marker = ctx.extras["update_marker"]
    updates = invoke_json(["update", "list", "--item", str(ctx.extras["item_id"])])
    for u in updates:
        body = (u.get("text_body") or "") + str(u.get("body") or "")
        if marker in body:
            return True
    return False


task_post_update = Task(
    name="post_update",
    prompt_template=(
        "Post an update on item {item_id} that contains the exact phrase "
        "\"{update_marker}\" so a reviewer can find it later."
    ),
    setup=_t4_setup,
    predicate=_t4_predicate,
    max_turns=4,
)


# --- Task 5: export PM board to CSV -----------------------------------------


def _t5_setup(ctx: TaskContext) -> None:
    ctx.extras["csv_path"] = f"/tmp/eval-pm-{ctx.suffix}.csv"


def _t5_predicate(result: "EvalResult", ctx: TaskContext) -> bool:
    del result
    import csv
    import os.path
    csv_path = ctx.extras["csv_path"]
    if not os.path.exists(csv_path):
        return False
    with open(csv_path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return len(rows) >= 1


def _t5_cleanup(result: "EvalResult", ctx: TaskContext) -> None:
    del result
    import os.path
    csv_path = ctx.extras["csv_path"]
    if os.path.exists(csv_path):
        try:
            os.remove(csv_path)
        except OSError:
            pass


task_export_csv = Task(
    name="export_csv",
    prompt_template=(
        "Export board {board_id} as CSV to the file {csv_path}. "
        "Confirm the file was written."
    ),
    setup=_t5_setup,
    predicate=_t5_predicate,
    cleanup_register=_t5_cleanup,
    max_turns=4,
)


# --- Task 6: URL → resource resolver ----------------------------------------


def _t6_setup(ctx: TaskContext) -> None:
    board = invoke_json(["board", "get", "--id", str(ctx.board_id)])
    ctx.extras["board_name"] = board.get("name", "")
    ctx.extras["board_url"] = f"https://playground.monday.com/boards/{ctx.board_id}"


def _t6_predicate(result: "EvalResult", ctx: TaskContext) -> bool:
    saw_board_get = any(
        re.search(r"\bmondo\s+board\s+get\b", c) and str(ctx.board_id) in c
        for c in result.bash_calls
    )
    if not saw_board_get:
        return False
    text_lower = result.final_text.lower()
    return "board" in text_lower and bool(ctx.extras["board_name"]) and (
        ctx.extras["board_name"].lower() in text_lower
    )


task_resolve_url = Task(
    name="resolve_url",
    prompt_template=(
        "What does the URL {board_url} point to? "
        "Identify whether it's a board or a workdoc, and report its name."
    ),
    setup=_t6_setup,
    predicate=_t6_predicate,
    max_turns=5,
)


ALL_TASKS: list[Task] = [
    task_list_boards,
    task_create_group,
    task_set_status,
    task_post_update,
    task_export_csv,
    task_resolve_url,
]


def workspace_id_for_eval() -> int:
    return playground_workspace_id()


def smoke_check_invoke() -> None:
    """Sanity probe: ensure mondo CLI is reachable. Used as a pre-flight."""
    result = invoke(["--version"], expect_exit=None)
    if result.exit_code != 0:
        raise RuntimeError(f"mondo --version failed: {result.stdout!r} {result.stderr!r}")
