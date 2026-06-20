"""Live integration tests for the cache expansion (Phases 1-4).

Each test re-enables the cache on top of the default `live_workspace_id`
env (which disables it), asserts the expected on-disk cache file is
written by a read, and verifies the invalidation contract by triggering
a mutation and re-checking. Returned data is checked against the live
API on the cache-hit path so we know the cache isn't lying.

Gated by `MONDAY_TEST_TOKEN`; the playground board/doc env vars
(`MONDO_TEST_BOARD_ID`, `MONDO_TEST_DOC_ID`) gate the per-board / per-doc
phases.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from ._helpers import CleanupPlan, invoke, invoke_json
from .conftest import PmBoard


def _cache_root(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Re-enable the cache and return its on-disk root (`<dir>/default/`).

    The `live_workspace_id` fixture sets `MONDO_CACHE_ENABLED=false`; this
    flips it back on for the rest of the test.
    """
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")
    cache_dir = os.environ["MONDO_CACHE_DIR"]
    return Path(cache_dir) / "default"


@pytest.mark.integration
def test_live_cache_workspace_get_short_circuits(
    live_workspace_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 1: `workspace list` warms the directory; `workspace get` reuses it."""
    cache_root = _cache_root(monkeypatch)
    workspaces_file = cache_root / "workspaces.json"

    # Warm the directory cache via a list. --refresh-cache writes through
    # even if a stale file is lurking.
    invoke(["workspace", "list", "--refresh-cache"])
    assert workspaces_file.exists(), "workspaces directory cache wasn't written"

    # `workspace get` should serve from cache. Compare against a forced-live
    # refetch to confirm shape parity.
    cached = invoke_json(["workspace", "get", "--id", str(live_workspace_id)])
    live = invoke_json(["workspace", "get", "--id", str(live_workspace_id), "--no-cache"])
    assert cached["id"] == live["id"]
    assert cached["name"] == live["name"]


@pytest.mark.integration
def test_live_cache_tags_invalidated_on_create_or_get(
    live_test_board_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 2: `tag list` writes `tags.json`; `tag create-or-get` drops it."""
    cache_root = _cache_root(monkeypatch)
    tags_file = cache_root / "tags.json"

    invoke(["tag", "list", "--refresh-cache"])
    assert tags_file.exists(), "tags directory cache wasn't written"

    # Mint a tag (or get an existing one with this name). Either way, the
    # cache file should be dropped by `invalidate_entity(opts, "tags")`.
    # Use a stable name so `create-or-get` is idempotent across runs: there
    # is no `tag delete` CLI path, so a unique name would leak a new tag onto
    # the shared board every run. The name's uniqueness isn't load-bearing —
    # any create-or-get call proves the cache invalidation.
    tag_name = "e2e-cache-tag"
    invoke(["tag", "create-or-get", "--name", tag_name, "--board", str(live_test_board_id)])
    assert not tags_file.exists(), "tag create-or-get did not invalidate tags cache"


@pytest.mark.integration
def test_live_cache_board_details_invalidated_on_structural_mutation(
    pm_board_session: PmBoard,
    cleanup_plan: CleanupPlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 3: `board get` writes `board_details/<id>.json`; a structural
    group mutation (handled by `invalidate_groups_cache`) drops it."""
    pm = pm_board_session
    cache_root = _cache_root(monkeypatch)
    details_file = cache_root / "board_details" / f"{pm.board_id}.json"

    # First read warms the per-board details cache.
    cached = invoke_json(["board", "get", "--id", str(pm.board_id)])
    assert details_file.exists(), "board_details cache file wasn't written"
    assert int(cached["id"]) == pm.board_id

    # Sanity: shape parity with a live re-fetch.
    live = invoke_json(["board", "get", "--id", str(pm.board_id), "--no-cache"])
    assert cached["name"] == live["name"]

    # Trigger structural mutation: create a scratch group, then delete it.
    # Either side drops `board_details/<board_id>` via `invalidate_groups_cache`.
    group_name = f"E2E Cache {uuid.uuid4().hex[:6]}"
    group = invoke_json(["group", "create", "--board", str(pm.board_id), "--name", group_name])
    group_id = group["id"]
    cleanup_plan.add(
        f"cache test group {group_id}",
        "group",
        "delete",
        "--board",
        str(pm.board_id),
        "--id",
        group_id,
        "--hard",
    )
    assert not details_file.exists(), "group create did not invalidate board_details cache"

    # Reading again rebuilds the cache file.
    invoke_json(["board", "get", "--id", str(pm.board_id)])
    assert details_file.exists(), "board_details cache file wasn't re-warmed"


@pytest.mark.integration
def test_live_cache_items_invalidated_on_column_set(
    pm_board_session: PmBoard,
    cleanup_plan: CleanupPlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4: `item get` writes `items/<id>.json`; `column set` drops it."""
    pm = pm_board_session
    cache_root = _cache_root(monkeypatch)

    # Use a scratch item so other tests sharing pm_board_session aren't affected.
    suffix = uuid.uuid4().hex[:8]
    created = invoke_json(
        [
            "item",
            "create",
            "--board",
            str(pm.board_id),
            "--group",
            pm.group_ids["backlog"],
            "--name",
            f"E2E Cache Item {suffix}",
        ]
    )
    item_id = int(created["id"])
    cleanup_plan.add(
        f"cache test item {item_id}",
        "item",
        "delete",
        "--id",
        str(item_id),
        "--hard",
    )

    items_file = cache_root / "items" / f"{item_id}.json"

    # First read warms the per-item cache.
    cached = invoke_json(["item", "get", "--id", str(item_id)])
    assert items_file.exists(), "items cache file wasn't written"
    assert int(cached["id"]) == item_id

    # Mutate a column on the item — invalidates `items/<id>` per the
    # `column set` callsite.
    invoke(
        [
            "column",
            "set",
            "--item",
            str(item_id),
            "--column",
            pm.column_ids["text"],
            "--value",
            f"cache-{suffix}",
        ]
    )
    assert not items_file.exists(), "column set did not invalidate items cache"

    # Re-read picks up the new value and re-warms the cache.
    re_read = invoke_json(["item", "get", "--id", str(item_id)])
    text_col = next(
        (c for c in re_read.get("column_values") or [] if c["id"] == pm.column_ids["text"]),
        None,
    )
    assert text_col is not None and text_col.get("text") == f"cache-{suffix}", re_read
    assert items_file.exists()


@pytest.mark.integration
def test_live_cache_docs_blocks_round_trip(
    live_workspace_id: int,
    cleanup_plan: CleanupPlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4: `doc get` writes `docs_blocks/<id>.json` and returns the same
    block tree on the next read; `doc add-markdown` invalidates the cache."""
    cache_root = _cache_root(monkeypatch)
    suffix = uuid.uuid4().hex[:8]

    created = invoke_json(
        [
            "doc",
            "create",
            "--workspace",
            str(live_workspace_id),
            "--name",
            f"E2E Cache Doc {suffix}",
        ]
    )
    doc_id = int(created["id"])
    cleanup_plan.add(f"cache test doc {doc_id}", "doc", "delete", "--doc", str(doc_id))

    blocks_file = cache_root / "docs_blocks" / f"{doc_id}.json"

    cached = invoke_json(["doc", "get", "--id", str(doc_id)])
    assert blocks_file.exists(), "docs_blocks cache file wasn't written"
    assert int(cached["id"]) == doc_id
    block_ids_before = [b.get("id") for b in cached.get("blocks") or []]

    # Append content → invalidates `docs_blocks/<doc_id>`.
    invoke(
        [
            "doc",
            "add-markdown",
            "--doc",
            str(doc_id),
            "--markdown",
            f"# Cache test {suffix}\n",
        ]
    )
    assert not blocks_file.exists(), "doc add-markdown did not invalidate docs_blocks cache"

    # Re-read picks up the new block and re-warms the cache.
    refreshed = invoke_json(["doc", "get", "--id", str(doc_id)])
    block_ids_after = [b.get("id") for b in refreshed.get("blocks") or []]
    assert len(block_ids_after) > len(block_ids_before), (
        "doc add-markdown didn't add visible blocks"
    )
    assert blocks_file.exists()


@pytest.mark.integration
def test_live_cache_updates_invalidated_on_create(
    pm_board_session: PmBoard,
    cleanup_plan: CleanupPlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 4: `update list --item <id>` writes `updates/<id>.json`; an
    `update create` on that item drops the cache."""
    pm = pm_board_session
    cache_root = _cache_root(monkeypatch)

    suffix = uuid.uuid4().hex[:8]
    item_id = pm.item_ids[0]

    # Warm the per-item updates cache.
    invoke_json(["update", "list", "--item", str(item_id)])
    updates_file = cache_root / "updates" / f"{item_id}.json"
    assert updates_file.exists(), "updates cache file wasn't written"

    update = invoke_json(
        [
            "update",
            "create",
            "--item",
            str(item_id),
            "--body",
            f"cache-test-{suffix}",
        ]
    )
    update_id = int(update["id"])
    cleanup_plan.add(
        f"cache test update {update_id}",
        "update",
        "delete",
        "--id",
        str(update_id),
    )
    assert not updates_file.exists(), "update create did not invalidate updates cache"


@pytest.mark.integration
def test_live_cache_board_items_round_trip(
    pm_board_session: PmBoard,
    cleanup_plan: CleanupPlan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#21: bare `item list --board X` writes `board_items/<board>.json`,
    a repeat list serves from it, and an item write on the board drops it."""
    pm = pm_board_session
    cache_root = _cache_root(monkeypatch)
    board_items_file = cache_root / "board_items" / f"{pm.board_id}.json"

    # Warm: bare list writes the cache.
    listed = invoke_json(["item", "list", "--board", str(pm.board_id), "--refresh-cache"])
    assert board_items_file.exists(), "board_items cache file wasn't written"

    # Repeat list serves the same rows from cache.
    cached = invoke_json(["item", "list", "--board", str(pm.board_id)])
    assert [r["id"] for r in cached] == [r["id"] for r in listed]

    # The --group variant filters the cached full list client-side; parity
    # with a forced-live group listing.
    group_id = pm.group_ids["backlog"]
    from_cache = invoke_json(["item", "list", "--board", str(pm.board_id), "--group", group_id])
    live = invoke_json(
        ["item", "list", "--board", str(pm.board_id), "--group", group_id, "--no-cache"]
    )
    assert {r["id"] for r in from_cache} == {r["id"] for r in live}

    # An item write on the board drops the cache file.
    suffix = uuid.uuid4().hex[:8]
    created = invoke_json(
        [
            "item",
            "create",
            "--board",
            str(pm.board_id),
            "--group",
            group_id,
            "--name",
            f"E2E BoardItems Cache {suffix}",
        ]
    )
    item_id = int(created["id"])
    cleanup_plan.add(
        f"board_items cache test item {item_id}",
        "item",
        "delete",
        "--id",
        str(item_id),
        "--hard",
    )
    assert not board_items_file.exists(), "item create did not invalidate the board_items cache"

    # Re-list sees the new item and re-warms the cache.
    re_listed = invoke_json(["item", "list", "--board", str(pm.board_id)])
    assert any(int(r["id"]) == item_id for r in re_listed), re_listed
    assert board_items_file.exists()


@pytest.mark.integration
def test_live_cache_status_refresh_clear_cli(
    live_workspace_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `cache status` / `cache refresh` / `cache clear` management commands."""
    del live_workspace_id
    cache_root = _cache_root(monkeypatch)
    workspaces_file = cache_root / "workspaces.json"

    # Warm the workspaces directory cache.
    invoke(["workspace", "list", "--refresh-cache"])
    assert workspaces_file.exists()

    # `cache status` reports on the cache files (smoke: exit 0, non-empty).
    status = invoke(["cache", "status"])
    assert status.exit_code == 0 and status.stdout.strip()

    # `cache clear workspaces` removes the file; idempotent.
    invoke(["cache", "clear", "workspaces"])
    assert not workspaces_file.exists(), "cache clear did not remove workspaces.json"

    # `cache refresh workspaces` re-fetches and rewrites it.
    invoke(["cache", "refresh", "workspaces"])
    assert workspaces_file.exists(), "cache refresh did not rewrite workspaces.json"
