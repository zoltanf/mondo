"""Shared post-fetch decoration for `board list` and `doc list`.

Both commands enrich rows with `workspace_name` and optionally attach/strip
url fields. Live-path and cache-path code funnel through the same helpers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

from mondo.api.errors import MondoError

if TYPE_CHECKING:
    from mondo.cli.context import GlobalOpts


def enrich_workspaces_best_effort(
    entries: list[dict[str, Any]], opts: GlobalOpts
) -> None:
    """Add `workspace_name` to each entry; swallow MondoError silently."""
    from mondo.cache.directory import enrich_workspace_names

    try:
        store = opts.build_cache_store("workspaces")
        with opts.build_client() as client:
            enrich_workspace_names(entries, client=client, store=store)
    except MondoError:
        pass


def apply_board_urls(
    entries: list[dict[str, Any]], opts: GlobalOpts
) -> None:
    """Attach a synthesized monday `url` to each board entry."""
    from mondo.cli._url import board_url, get_tenant_slug

    try:
        with opts.build_client() as client:
            slug = get_tenant_slug(client)
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    for b in entries:
        try:
            bid = int(b.get("id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        b["url"] = board_url(slug, bid)


def strip_url_fields(entries: list[dict[str, Any]]) -> None:
    """Drop `url` and `relative_url` from every entry."""
    for entry in entries:
        entry.pop("url", None)
        entry.pop("relative_url", None)
