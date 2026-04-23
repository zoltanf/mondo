"""`mondo cache` command group: inspect, refresh, and clear the local
directory cache for boards/workspaces/users/teams/docs/folders/columns/groups."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum
from typing import Any

import typer

from mondo.api.errors import MondoError
from mondo.cache.directory import (
    get_boards,
    get_columns,
    get_docs,
    get_folders,
    get_groups,
    get_teams,
    get_users,
    get_workspaces,
)
from mondo.cache.store import CacheStore
from mondo.cli._examples import epilog_for
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class CacheType(StrEnum):
    boards = "boards"
    workspaces = "workspaces"
    users = "users"
    teams = "teams"
    docs = "docs"
    folders = "folders"
    columns = "columns"
    groups = "groups"
    all = "all"


_SINGLE_FILE_TYPES: tuple[str, ...] = ("boards", "workspaces", "users", "teams", "docs", "folders")
_SCOPED_TYPES: tuple[str, ...] = ("columns", "groups")
_ALL_TYPES: tuple[str, ...] = (*_SINGLE_FILE_TYPES, *_SCOPED_TYPES)

_REFRESH_DISPATCH = {
    "boards": get_boards,
    "workspaces": get_workspaces,
    "users": get_users,
    "teams": get_teams,
    "docs": get_docs,
    "folders": get_folders,
}


def _resolve_types(selector: CacheType) -> list[str]:
    if selector is CacheType.all:
        return list(_ALL_TYPES)
    return [selector.value]


def _scoped_board_ids(opts: GlobalOpts, entity: str) -> list[str]:
    """Return board ids already present in a scoped cache directory.

    Scans `<cache_dir>/<entity>/*.json`. Missing dir → empty list. Ignores
    hidden tempfiles. Order is sorted lexicographically for stable output.
    """
    resolved = opts.resolve_cache_config()
    scoped_dir = resolved.directory / entity
    if not scoped_dir.exists():
        return []
    ids: list[str] = []
    for p in scoped_dir.glob("*.json"):
        if p.name.startswith("."):
            continue
        ids.append(p.stem)
    ids.sort()
    return ids


def _format_age(age: timedelta | None) -> str | None:
    if age is None:
        return None
    seconds = int(age.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours}h{minutes:02d}m" if minutes else f"{hours}h"


@app.command("status", epilog=epilog_for("cache status"))
def status_cmd(
    ctx: typer.Context,
    cache_type: CacheType = typer.Argument(
        CacheType.all,
        help="Entity type to inspect (default: all).",
        case_sensitive=False,
    ),
) -> None:
    """Show age / freshness / entry count for each cache file.

    For `columns`/`groups`, one row per board already present in that scoped
    cache directory.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    rows: list[dict[str, Any]] = []
    for entity in _resolve_types(cache_type):
        if entity in _SCOPED_TYPES:
            rows.extend(_status_rows_for_scoped(opts, entity))
        else:
            rows.append(_status_row(opts, entity))
    opts.emit(rows)


def _status_row(
    opts: GlobalOpts, entity: str, *, scope: str | None = None
) -> dict[str, Any]:
    store = opts.build_cache_store(entity, scope=scope)
    cached = store.read()
    fetched_at: str | None
    age: timedelta | None
    if cached is not None:
        fetched_at = cached.fetched_at.isoformat().replace("+00:00", "Z")
        age = cached.age
    else:
        # Only touch disk again when we don't already have a parsed envelope.
        age = store.age()
        fetched_at = _lookup_fetched_at(store) if age is not None else None
    row: dict[str, Any] = {
        "type": entity,
        "path": str(store.path),
        "fetched_at": fetched_at,
        "age": _format_age(age),
        "ttl_seconds": store.ttl_seconds,
        "fresh": cached is not None,
        "entries": len(cached.entries) if cached is not None else None,
    }
    if scope is not None:
        row["board"] = scope
    return row


def _status_rows_for_scoped(opts: GlobalOpts, entity: str) -> list[dict[str, Any]]:
    board_ids = _scoped_board_ids(opts, entity)
    return [_status_row(opts, entity, scope=bid) for bid in board_ids]


def _lookup_fetched_at(store: CacheStore) -> str | None:
    """Best-effort read of fetched_at from an expired or endpoint-mismatched
    envelope, for status reporting. Returns None on any failure."""
    import json as _json

    try:
        raw = _json.loads(store.path.read_text(encoding="utf-8"))
        value = raw.get("fetched_at")
        if isinstance(value, str):
            return value
    except (OSError, ValueError, KeyError, AttributeError):
        return None
    return None


@app.command("refresh", epilog=epilog_for("cache refresh"))
def refresh_cmd(
    ctx: typer.Context,
    cache_type: CacheType = typer.Argument(
        CacheType.all,
        help="Entity type(s) to refresh (default: all).",
        case_sensitive=False,
    ),
    boards: list[int] = typer.Option(
        [],
        "--board",
        help=(
            "Board id(s) to refresh (columns/groups only; repeatable). "
            "Omit to refresh every board already present in the selected scoped cache."
        ),
    ),
) -> None:
    """Force-fetch the selected cache(s) and rewrite disk.

    For `columns`/`groups`, refreshes one file per board id. Without `--board`,
    refreshes every board already cached on disk per selected scoped type
    (does not discover additional boards on the account).
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    types = _resolve_types(cache_type)

    if boards and not any(t in _SCOPED_TYPES for t in types):
        typer.secho(
            "error: --board only applies when refreshing `columns` or `groups`.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    if opts.dry_run:
        dry: list[dict[str, Any]] = []
        for t in types:
            if t in _SCOPED_TYPES:
                target_ids = [str(b) for b in boards] or _scoped_board_ids(opts, t)
                for bid in target_ids:
                    dry.append({"type": t, "board": bid, "action": "refresh"})
            else:
                dry.append({"type": t, "action": "refresh"})
        opts.emit(dry)
        raise typer.Exit(0)

    try:
        client = opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    results: list[dict[str, Any]] = []
    try:
        with client:
            for entity in types:
                if entity in _SCOPED_TYPES:
                    results.extend(_refresh_scoped(opts, client, boards, entity))
                    continue
                store = opts.build_cache_store(entity)
                fetcher = _REFRESH_DISPATCH[entity]
                cached = fetcher(client, store=store, refresh=True)
                results.append(
                    {
                        "type": entity,
                        "fetched_at": cached.fetched_at.isoformat().replace("+00:00", "Z"),
                        "count": len(cached.entries),
                    }
                )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    opts.emit(results)


def _for_each_board_scope(
    opts: GlobalOpts,
    boards: list[int],
    entity: str,
    op: Callable[[CacheStore, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply `op(store, board_id)` to every target scoped cache file.

    Target set is the explicit `boards` list if given, otherwise every board
    already present in the selected scoped cache directory.
    """
    target_ids: list[str] = [str(b) for b in boards] if boards else _scoped_board_ids(opts, entity)
    return [op(opts.build_cache_store(entity, scope=bid), bid) for bid in target_ids]


_SCOPED_REFRESH_DISPATCH = {
    "columns": get_columns,
    "groups": get_groups,
}


def _refresh_scoped(
    opts: GlobalOpts, client: Any, boards: list[int], entity: str
) -> list[dict[str, Any]]:
    def _one(store: CacheStore, bid: str) -> dict[str, Any]:
        fetcher = _SCOPED_REFRESH_DISPATCH[entity]
        cached = fetcher(client, store=store, board_id=int(bid), refresh=True)
        return {
            "type": entity,
            "board": bid,
            "fetched_at": cached.fetched_at.isoformat().replace("+00:00", "Z"),
            "count": len(cached.entries),
        }

    return _for_each_board_scope(opts, boards, entity, _one)


@app.command("clear", epilog=epilog_for("cache clear"))
def clear_cmd(
    ctx: typer.Context,
    cache_type: CacheType = typer.Argument(
        CacheType.all,
        help="Entity type(s) to clear (default: all).",
        case_sensitive=False,
    ),
    boards: list[int] = typer.Option(
        [],
        "--board",
        help=(
            "Board id(s) to clear (columns/groups only; repeatable). "
            "Omit to clear every per-board scoped cache for the selected types."
        ),
    ),
) -> None:
    """Delete the selected cache file(s). Idempotent.

    For `columns`/`groups`, removes one file per board id; omit `--board` to
    clear every per-board scoped cache for the selected types.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    types = _resolve_types(cache_type)

    if boards and not any(t in _SCOPED_TYPES for t in types):
        typer.secho(
            "error: --board only applies when clearing `columns` or `groups`.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    results: list[dict[str, Any]] = []
    for entity in types:
        if entity in _SCOPED_TYPES:
            results.extend(_clear_scoped(opts, boards, entity))
            continue
        store = opts.build_cache_store(entity)
        path = str(store.path)
        if opts.dry_run:
            results.append({"type": entity, "path": path, "action": "clear"})
            continue
        removed = store.invalidate()
        results.append({"type": entity, "path": path, "removed": removed})
    opts.emit(results)


def _clear_scoped(opts: GlobalOpts, boards: list[int], entity: str) -> list[dict[str, Any]]:
    def _one(store: CacheStore, bid: str) -> dict[str, Any]:
        path = str(store.path)
        if opts.dry_run:
            return {"type": entity, "board": bid, "path": path, "action": "clear"}
        return {
            "type": entity,
            "board": bid,
            "path": path,
            "removed": store.invalidate(),
        }

    return _for_each_board_scope(opts, boards, entity, _one)
