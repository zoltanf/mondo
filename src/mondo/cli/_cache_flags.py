"""Shared cache-flag plumbing for CLI list commands.

Several list commands accept `--no-cache`, `--refresh-cache`, and
`--fuzzy-threshold`. The mutex check, fuzzy-threshold resolution, and the
"is cache actually in play for this invocation" computation were
copy-pasted in each caller. This module centralizes them.
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from mondo.cache import ResolvedCacheConfig
from mondo.cli.context import GlobalOpts


def reject_mutually_exclusive(no_cache: bool, refresh_cache: bool) -> None:
    """Exit(2) with a uniform error when both `--no-cache` and `--refresh-cache` are set."""
    if no_cache and refresh_cache:
        typer.secho(
            "error: --no-cache and --refresh-cache are mutually exclusive.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)


@dataclass(frozen=True)
class CachePrefs:
    cfg: ResolvedCacheConfig
    use_cache: bool
    fuzzy_threshold: int


def resolve_cache_prefs(
    opts: GlobalOpts,
    *,
    no_cache: bool,
    fuzzy_threshold: int | None,
    extra_disable: bool = False,
) -> CachePrefs:
    """Resolve the cache config and fold `--no-cache` / `--fuzzy-threshold` in.

    `extra_disable` covers command-specific reasons to skip the cache even
    when the user didn't pass `--no-cache` (e.g. `board list --with-item-counts`
    which needs live data).
    """
    cfg = opts.resolve_cache_config()
    use_cache = cfg.enabled and not no_cache and not extra_disable
    threshold = fuzzy_threshold if fuzzy_threshold is not None else cfg.fuzzy_threshold
    return CachePrefs(cfg=cfg, use_cache=use_cache, fuzzy_threshold=threshold)
