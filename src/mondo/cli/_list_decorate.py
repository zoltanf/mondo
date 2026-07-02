"""Shared post-fetch decoration for `board list` and `doc list`.

Both commands enrich rows with `workspace_name` and optionally attach/strip
url fields. Live-path and cache-path code funnel through the same helpers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mondo.api.errors import MondoError
from mondo.cli._exec import handle_mondo_error_or_exit

if TYPE_CHECKING:
    from mondo.cli.context import GlobalOpts


def enrich_workspaces_best_effort(entries: list[dict[str, Any]], opts: GlobalOpts) -> None:
    """Add `workspace_name` to each entry; swallow MondoError silently."""
    from mondo.cache.directory import enrich_workspace_names

    try:
        store = opts.build_cache_store("workspaces")
        with opts.build_client() as client:
            enrich_workspace_names(entries, client=client, store=store)
    except MondoError:
        pass


def _apply_urls(
    entries: list[dict[str, Any]],
    opts: GlobalOpts,
    make_url: Callable[[str, int], str],
) -> None:
    """Resolve the tenant slug once, then set `url` on each entry with a
    numeric id via `make_url(slug, entry_id)`."""
    from mondo.cli._url import get_tenant_slug

    try:
        with opts.build_client() as client:
            slug = get_tenant_slug(client)
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    for entry in entries:
        try:
            entry_id = int(entry.get("id"))  # type: ignore[arg-type]
        except TypeError, ValueError:
            continue
        entry["url"] = make_url(slug, entry_id)


def apply_board_urls(entries: list[dict[str, Any]], opts: GlobalOpts) -> None:
    """Attach a synthesized monday `url` to each board entry."""
    from mondo.cli._url import board_url

    _apply_urls(entries, opts, board_url)


def apply_item_urls(entries: list[dict[str, Any]], opts: GlobalOpts, *, board_id: int) -> None:
    """Attach a synthesized monday `url` to each item entry."""
    from mondo.cli._url import item_url

    _apply_urls(entries, opts, lambda slug, item_id: item_url(slug, board_id, item_id))


def strip_url_fields(entries: list[dict[str, Any]]) -> None:
    """Drop `url` and `relative_url` from every entry."""
    for entry in entries:
        entry.pop("url", None)
        entry.pop("relative_url", None)
