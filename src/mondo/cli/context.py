"""GlobalOpts — the typed context object attached to every Typer command.

A command reads it via `ctx.obj: GlobalOpts = ctx.ensure_object(GlobalOpts)`
or uses the helper `build_client(opts)` to get a ready-to-use MondayClient.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from mondo.api.auth import ResolvedToken
    from mondo.api.client import MondayClient
    from mondo.cache import CacheStore, ResolvedCacheConfig
    from mondo.cache.store import EntityType
    from mondo.config.schema import Config


@dataclass
class GlobalOpts:
    """Carries parsed global options from the root Typer callback.

    One instance per Typer invocation; `load_config()` is memoized on the
    instance so sequential `resolve_token` / `build_client` /
    `resolve_cache_config` / `api_endpoint` calls don't re-read the YAML each
    time.
    """

    profile_name: str | None
    flag_token: str | None
    flag_api_version: str | None
    verbose: bool
    debug: bool
    output: str | None = None
    query: str | None = None
    fields: str | None = None
    yes: bool = False
    dry_run: bool = False
    # True once `emit()` has written to stdout. The fatal-error stdout
    # mirror (#25) checks this so a partial-success stream is never
    # corrupted by a trailing error envelope.
    stdout_emitted: bool = field(default=False, init=False)
    _config: Config | None = field(default=None, init=False, repr=False)
    _cache_config: ResolvedCacheConfig | None = field(default=None, init=False, repr=False)

    def _load(self) -> Config:
        if self._config is None:
            from mondo.config.loader import load_config

            self._config = load_config()
        return self._config

    def emit(
        self,
        data: Any,
        *,
        stream: TextIO | None = None,
        default_tty_override: bool | None = None,
        selected_fields: frozenset[str] | None = None,
    ) -> None:
        """Render `data` to stdout (or `stream`) honoring --output and --query.

        Thin wrapper over `mondo.cli._render.render_output`; folds the returned
        "wrote to real stdout" flag back into `self.stdout_emitted`.
        """
        from mondo.cli._render import render_output

        wrote = render_output(
            data,
            output=self.output,
            query=self.query,
            fields=self.fields,
            stream=stream,
            default_tty_override=default_tty_override,
            selected_fields=selected_fields,
        )
        if wrote:
            self.stdout_emitted = True

    def resolve_token(self) -> ResolvedToken:
        """Run the token resolution chain using this invocation's options."""
        from mondo.cli._client_factory import resolve_token_from_config

        return resolve_token_from_config(
            self._load(), profile_name=self.profile_name, flag_token=self.flag_token
        )

    def build_client(self) -> MondayClient:
        """Convenience: resolve the token, pick the API version, build the client."""
        from mondo.cli._client_factory import build_client_from_config

        return build_client_from_config(
            self._load(),
            profile_name=self.profile_name,
            flag_token=self.flag_token,
            flag_api_version=self.flag_api_version,
        )

    def resolve_cache_config(self) -> ResolvedCacheConfig:
        """Resolve the fully-merged cache configuration for this invocation."""
        if self._cache_config is None:
            from mondo.cache import resolve_cache_config

            self._cache_config = resolve_cache_config(self._load(), profile_name=self.profile_name)
        return self._cache_config

    def api_endpoint(self) -> str:
        """Effective monday API endpoint for the current profile.

        Used as the `api_endpoint` key for cache envelopes so switching profiles
        (e.g. to a different monday account) doesn't serve stale data.
        """
        from mondo.cli._client_factory import api_endpoint_from_config

        return api_endpoint_from_config(self._load(), profile_name=self.profile_name)

    def columns_cache_store(
        self, board_id: int, *, no_cache: bool = False
    ) -> CacheStore | None:
        """Per-board columns store for reads, or ``None`` when the cache is off.

        Returns ``None`` when caching is disabled (config) or suppressed for
        this call (`--no-cache`), signalling callers/`fetch_board_columns` to
        take the live path.
        """
        if no_cache or not self.resolve_cache_config().enabled:
            return None
        return self.build_cache_store("columns", scope=str(board_id))

    def columns_cache_store_for_invalidation(self, board_id: int) -> CacheStore | None:
        """Per-board columns store to invalidate after a mutation, or ``None``.

        Returns ``None`` on `--dry-run` (no state changed) so callers pass it
        straight to `invalidate_columns_cache` as a no-op.
        """
        if self.dry_run:
            return None
        return self.build_cache_store("columns", scope=str(board_id))

    def build_cache_store(self, entity_type: EntityType, *, scope: str | None = None) -> CacheStore:
        """Build a CacheStore for the given entity type, wired with the
        resolved TTL + endpoint + cache directory.

        `scope` turns the store into a per-scope file at
        `<cache_dir>/<entity_type>/<scope>.json` (e.g. per-board for columns).
        """
        from mondo.cache import CacheStore

        resolved = self.resolve_cache_config()
        return CacheStore(
            entity_type=entity_type,
            cache_dir=resolved.directory,
            api_endpoint=self.api_endpoint(),
            ttl_seconds=resolved.ttl_for(entity_type),
            scope=scope,
        )
