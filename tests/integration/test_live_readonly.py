"""Live integration tests for read-only / informational commands that
don't mutate anything: `account`, `me`, `auth whoami`, `schema`,
`complexity status`, `favorite list`, `graphql` (read query),
`aggregate board`, and `activity board`.

These never write — `account`/`me`/`schema` etc. use the function-scoped
`live_workspace_id` fixture only for its token + env setup; the board
aggregations run against the fresh session PM board.
"""

from __future__ import annotations

import pytest

from ._helpers import invoke, invoke_json
from .conftest import PmBoard


@pytest.mark.integration
def test_live_account(live_workspace_id: int) -> None:
    del live_workspace_id
    acct = invoke_json(["account"])
    assert acct.get("id") and acct.get("name"), acct
    assert "plan" in acct and "products" in acct


@pytest.mark.integration
def test_live_me(live_workspace_id: int) -> None:
    del live_workspace_id
    me = invoke_json(["me"])
    assert me.get("id") and me.get("name")
    assert "teams" in me and "account" in me


@pytest.mark.integration
def test_live_auth_whoami(live_workspace_id: int) -> None:
    del live_workspace_id
    who = invoke_json(["auth", "whoami"])
    assert who.get("id") and who.get("email")
    assert "account" in who


@pytest.mark.integration
def test_live_complexity_status(live_workspace_id: int) -> None:
    del live_workspace_id
    status = invoke_json(["complexity", "status"])
    # Fires one cheap query, so budget keys must be populated.
    assert "budget_after" in status and "reset_in_seconds" in status


@pytest.mark.integration
def test_live_schema_all_and_resource(live_workspace_id: int) -> None:
    del live_workspace_id
    all_schema = invoke_json(["schema"])
    assert "board" in all_schema and "item" in all_schema
    board_schema = invoke_json(["schema", "board"])
    # Read fields selected for `board get`.
    assert "columns" in board_schema.get("get", [])


@pytest.mark.integration
def test_live_help_topics(live_workspace_id: int) -> None:
    """`mondo help` lists prose topics; `mondo help <topic>` reads one."""
    del live_workspace_id
    listing = invoke(["help"])
    assert listing.exit_code == 0 and listing.stdout.strip()
    topic = invoke(["help", "codecs"])
    assert topic.exit_code == 0 and "codec" in topic.stdout.lower()


@pytest.mark.integration
def test_live_favorite_list(live_workspace_id: int) -> None:
    del live_workspace_id
    favs = invoke_json(["favorite", "list"])
    assert isinstance(favs, list)


@pytest.mark.integration
def test_live_graphql_read_query(live_workspace_id: int) -> None:
    """Raw passthrough returns monday's `{data: {...}}` envelope."""
    del live_workspace_id
    out = invoke_json(["graphql", "query { me { id name } }"])
    assert out["data"]["me"]["id"], out


@pytest.mark.integration
def test_live_aggregate_board(pm_board_session: PmBoard) -> None:
    """COUNT:* over the board, plus a grouped SUM on the numbers column."""
    pm = pm_board_session
    count = invoke_json(["aggregate", "board", "--board", str(pm.board_id), "--select", "COUNT:*"])
    assert count and count[0]["count"] >= len(pm.item_ids)

    grouped = invoke_json(
        [
            "aggregate",
            "board",
            "--board",
            str(pm.board_id),
            "--group-by",
            pm.column_ids["status"],
            "--select",
            f"SUM:{pm.column_ids['numbers']}",
        ]
    )
    assert isinstance(grouped, list) and grouped, grouped


@pytest.mark.integration
def test_live_activity_board(pm_board_session: PmBoard) -> None:
    """A freshly built board has recent activity-log entries (creates)."""
    pm = pm_board_session
    entries = invoke_json(["activity", "board", "--board", str(pm.board_id), "--max-items", "10"])
    assert isinstance(entries, list) and entries, "expected recent activity entries"
    assert all("event" in e for e in entries)
