"""`mondo cache` command group: inspect, refresh, and clear the local
directory cache for boards/workspaces/users/teams."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Any

import typer

from mondo.api.errors import MondoError
from mondo.cache.directory import (
    get_boards,
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
    all = "all"


_ALL_TYPES: tuple[str, ...] = ("boards", "workspaces", "users", "teams")

_REFRESH_DISPATCH = {
    "boards": get_boards,
    "workspaces": get_workspaces,
    "users": get_users,
    "teams": get_teams,
}


def _resolve_types(selector: CacheType) -> list[str]:
    if selector is CacheType.all:
        return list(_ALL_TYPES)
    return [selector.value]


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
    """Show age / freshness / entry count for each cache file."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    rows: list[dict[str, Any]] = []
    for entity in _resolve_types(cache_type):
        store = opts.build_cache_store(entity)  # type: ignore[arg-type]
        cached = store.read()
        age = store.age()
        rows.append(
            {
                "type": entity,
                "path": str(store.path),
                "fetched_at": (
                    cached.fetched_at.isoformat().replace("+00:00", "Z")
                    if cached is not None
                    else (_lookup_fetched_at(store) if age is not None else None)
                ),
                "age": _format_age(age),
                "ttl_seconds": store.ttl_seconds,
                "fresh": cached is not None,
                "entries": len(cached.entries) if cached is not None else None,
            }
        )
    opts.emit(rows)


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
) -> None:
    """Force-fetch the selected cache(s) and rewrite disk."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    types = _resolve_types(cache_type)

    if opts.dry_run:
        opts.emit([{"type": t, "action": "refresh"} for t in types])
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
                store = opts.build_cache_store(entity)  # type: ignore[arg-type]
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


@app.command("clear", epilog=epilog_for("cache clear"))
def clear_cmd(
    ctx: typer.Context,
    cache_type: CacheType = typer.Argument(
        CacheType.all,
        help="Entity type(s) to clear (default: all).",
        case_sensitive=False,
    ),
) -> None:
    """Delete the selected cache file(s). Idempotent."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    types = _resolve_types(cache_type)

    results: list[dict[str, Any]] = []
    for entity in types:
        store = opts.build_cache_store(entity)  # type: ignore[arg-type]
        path = str(store.path)
        if opts.dry_run:
            results.append({"type": entity, "path": path, "action": "clear"})
            continue
        removed = store.invalidate()
        results.append({"type": entity, "path": path, "removed": removed})
    opts.emit(results)
