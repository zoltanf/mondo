"""Live integration tests for the admin surfaces: users, teams, tags.

Read paths (`user list/get`, `team list/get`, `tag get`) run for real.
The *mutating* org-level commands (user role/activation/team-membership,
team create, workspace create/update/membership, webhook create, notify
send) are exercised via `--dry-run` only — they print the GraphQL
mutation + variables without sending, so no real users, teams,
workspaces, webhooks, or notifications are ever touched.
"""

from __future__ import annotations

import json
import uuid

import pytest

from ._helpers import invoke, invoke_json
from .conftest import PmBoard

# ---------------------------------------------------------------------------
# Read paths (real)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_user_list_and_get(live_workspace_id: int) -> None:
    del live_workspace_id
    users = invoke_json(["user", "list", "--max-items", "5", "--no-cache"])
    assert isinstance(users, list) and users, "expected at least one user"
    uid = users[0]["id"]
    got = invoke_json(["user", "get", "--id", str(uid)])
    assert str(got["id"]) == str(uid)
    assert "teams" in got and "account" in got


@pytest.mark.integration
def test_live_team_list_and_get(live_workspace_id: int) -> None:
    del live_workspace_id
    teams = invoke_json(["team", "list", "--max-items", "5", "--no-cache"])
    assert isinstance(teams, list)
    if not teams:
        pytest.skip("account has no teams to read")
    tid = teams[0]["id"]
    got = invoke_json(["team", "get", "--id", str(tid)])
    assert str(got["id"]) == str(tid)


@pytest.mark.integration
def test_live_tag_get_board_scoped(pm_board_session: PmBoard) -> None:
    """`tag create-or-get` mints a board-scoped tag; `tag get --board` reads it
    back (account-level `tags()` doesn't expose board-private tags)."""
    pm = pm_board_session
    name = f"e2etag{uuid.uuid4().hex[:6]}"
    created = invoke_json(["tag", "create-or-get", "--board", str(pm.board_id), "--name", name])
    tag_id = created["id"]
    got = invoke_json(["tag", "get", "--id", str(tag_id), "--board", str(pm.board_id)])
    assert str(got["id"]) == str(tag_id)
    assert got.get("name") == name


# ---------------------------------------------------------------------------
# Mutating org-level commands — dry-run only (never sent)
# ---------------------------------------------------------------------------

# (label, argv, expected mutation field name in the dry-run query)
_DRY_RUN_CASES: list[tuple[str, list[str], str]] = [
    (
        "user-update-role",
        ["user", "update-role", "--user", "123", "--role", "member"],
        "update_multiple_users_as_members",
    ),
    ("user-deactivate", ["user", "deactivate", "--user", "123"], "deactivate_users"),
    ("user-activate", ["user", "activate", "--user", "123"], "activate_users"),
    (
        "user-add-to-team",
        ["user", "add-to-team", "--team", "1", "--user", "2"],
        "add_users_to_team",
    ),
    (
        "user-remove-from-team",
        ["user", "remove-from-team", "--team", "1", "--user", "2"],
        "remove_users_from_team",
    ),
    (
        "team-create",
        ["team", "create", "--name", "E2E DryRun Team", "--allow-empty"],
        "create_team",
    ),
    ("team-delete", ["team", "delete", "--id", "1", "--hard"], "delete_team"),
    ("team-add-users", ["team", "add-users", "--team", "1", "--user", "2"], "add_users_to_team"),
    (
        "team-remove-users",
        ["team", "remove-users", "--team", "1", "--user", "2"],
        "remove_users_from_team",
    ),
    (
        "team-assign-owners",
        ["team", "assign-owners", "--team", "1", "--user", "2"],
        "assign_team_owners",
    ),
    (
        "team-remove-owners",
        ["team", "remove-owners", "--team", "1", "--user", "2"],
        "remove_team_owners",
    ),
    ("workspace-create", ["workspace", "create", "--name", "E2E DryRun WS"], "create_workspace"),
    (
        "workspace-update",
        ["workspace", "update", "--id", "1", "--name", "Renamed"],
        "update_workspace",
    ),
    ("workspace-delete", ["workspace", "delete", "--id", "1", "--hard"], "delete_workspace"),
    (
        "workspace-add-user",
        ["workspace", "add-user", "--id", "1", "--user", "2"],
        "add_users_to_workspace",
    ),
    (
        "workspace-remove-user",
        ["workspace", "remove-user", "--id", "1", "--user", "2"],
        "delete_users_from_workspace",
    ),
    (
        "workspace-add-team",
        ["workspace", "add-team", "--id", "1", "--team", "2"],
        "add_teams_to_workspace",
    ),
    (
        "workspace-remove-team",
        ["workspace", "remove-team", "--id", "1", "--team", "2"],
        "delete_teams_from_workspace",
    ),
    (
        "webhook-create",
        [
            "webhook",
            "create",
            "--board",
            "1",
            "--url",
            "https://e2e.example/hook",
            "--event",
            "create_item",
        ],
        "create_webhook",
    ),
    ("webhook-delete", ["webhook", "delete", "--id", "1"], "delete_webhook"),
    (
        "notify-send",
        ["notify", "send", "--user", "1", "--target", "2", "--text", "hi"],
        "create_notification",
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize("label,argv,mutation", _DRY_RUN_CASES, ids=[c[0] for c in _DRY_RUN_CASES])
def test_live_org_mutation_dry_run(
    live_workspace_id: int, label: str, argv: list[str], mutation: str
) -> None:
    """Each org-level mutation dispatches to the right GraphQL mutation, asserted
    via --dry-run so nothing is sent to monday."""
    del live_workspace_id, label
    out = invoke_json(["--dry-run", *argv])
    assert mutation in out["query"], f"expected {mutation} in:\n{out['query']}"
    assert "variables" in out
    # Sanity: the dry-run payload is valid JSON-serialisable (it already is,
    # invoke_json parsed it) and carries variables.
    assert isinstance(json.loads(json.dumps(out["variables"])), dict)


@pytest.mark.integration
def test_live_webhook_list(pm_board_session: PmBoard) -> None:
    """`webhook list` is a safe read; a fresh board simply has none."""
    pm = pm_board_session
    hooks = invoke_json(["webhook", "list", "--board", str(pm.board_id), "--no-cache"])
    assert isinstance(hooks, list)


@pytest.mark.integration
def test_live_validation_list(pm_board_session: PmBoard) -> None:
    """`validation list` reads a board's rule set (empty on a fresh board)."""
    pm = pm_board_session
    rules = invoke_json(["validation", "list", "--board", str(pm.board_id)])
    # monday returns the rule set as an object (required columns + rules).
    assert isinstance(rules, dict)


@pytest.mark.integration
@pytest.mark.parametrize(
    "argv",
    [
        ["validation", "create", "--board", "1", "--column", "status", "--rule-type", "required"],
        ["validation", "update", "--id", "1", "--description", "x"],
        ["validation", "delete", "--id", "1"],
    ],
    ids=["create", "update", "delete"],
)
def test_live_validation_crud_removed(live_workspace_id: int, argv: list[str]) -> None:
    """monday removed validation-rule CRUD in API 2026-01; the command guards
    with a clear usage error (exit 2) instead of sending anything."""
    del live_workspace_id
    result = invoke(argv, expect_exit=2)
    assert "2026-01" in result.stderr or "UI-only" in result.stderr, result.stderr
