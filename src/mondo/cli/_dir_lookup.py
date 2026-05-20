"""Single-entity GET via the existing directory cache.

CLI `<entity> get` commands whose payload shape matches the cached directory
entry (`workspaces`, `folders`, `teams`) can short-circuit through this helper
instead of going live every time. The directory cache is populated as a side
effect of a miss so subsequent calls hit, exactly like `<entity> list`.

Falls through to a caller-supplied `fetch_live` when the entry is absent from
the directory (just-created, restricted access, deleted entry being polled).
That keeps the contract identical to today's live path on the unhappy edges
where the directory and the single-entity GET disagree.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mondo.api.errors import MondoError
from mondo.cli._cache_flags import emit_cache_provenance, reject_mutually_exclusive
from mondo.cli._exec import client_or_exit, handle_mondo_error_or_exit

if TYPE_CHECKING:
    from mondo.api.client import MondayClient
    from mondo.cache.store import CachedDirectory
    from mondo.cli.context import GlobalOpts


DirectoryFetcher = Callable[..., "CachedDirectory"]
"""``fetcher(client, *, store, refresh)`` — one of the helpers in
`mondo.cache.directory` (e.g. `get_workspaces`)."""

LiveFetcher = Callable[["MondayClient"], "dict[str, Any] | None"]
"""``fetch_live(client) -> entry-or-None`` — the live GraphQL fallback."""


def lookup_entity_in_directory(
    opts: GlobalOpts,
    *,
    entity_type: str,
    target_id: int | str,
    no_cache: bool,
    refresh: bool,
    fetcher: DirectoryFetcher,
    fetch_live: LiveFetcher,
    explain_cache: bool = False,
) -> dict[str, Any] | None:
    """Resolve a single entity by id, preferring the directory cache.

    Behavior:
    * `no_cache=True` or cache globally disabled — call `fetch_live(client)`.
    * Otherwise consult the directory cache via `fetcher(client, store,
      refresh=refresh)`. When a fresh envelope is found, scan its entries
      for one whose stringified `id` matches `target_id`. On hit, return it
      and emit the standard `cache: hit` provenance line.
    * On directory-cache miss within an otherwise-fresh envelope, fall
      through to `fetch_live(client)` (handles brand-new entries the
      cache hasn't picked up yet). Result is returned but NOT written
      back to the directory.
    """
    reject_mutually_exclusive(no_cache, refresh)
    cfg = opts.resolve_cache_config()
    use_cache = cfg.enabled and not no_cache

    if not use_cache:
        client = client_or_exit(opts)
        try:
            with client:
                return fetch_live(client)
        except MondoError as e:
            handle_mondo_error_or_exit(e)

    target_key = str(target_id)
    client = client_or_exit(opts)
    store = opts.build_cache_store(entity_type)  # type: ignore[arg-type]
    try:
        with client:
            cached = fetcher(client, store=store, refresh=refresh)
            for entry in cached.entries:
                if str(entry.get("id")) == target_key:
                    emit_cache_provenance(
                        opts, cached, store=store, explain=explain_cache
                    )
                    return entry
            # Present in cache freshness window but absent from entries.
            # Fall through to a single-entity live fetch so a just-created
            # or just-shared resource is still resolvable without forcing
            # a full directory refresh.
            return fetch_live(client)
    except MondoError as e:
        handle_mondo_error_or_exit(e)
