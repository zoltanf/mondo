"""GlobalOpts — the typed context object attached to every Typer command.

A command reads it via `ctx.obj: GlobalOpts = ctx.ensure_object(GlobalOpts)`
or uses the helper `build_client(opts)` to get a ready-to-use MondayClient.
"""

from __future__ import annotations

import os
import sys
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
    yes: bool = False
    dry_run: bool = False
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

        Applies `--query` before formatting. Auto-picks the format based on
        whether stdout is a TTY if `--output` wasn't set.

        When `selected_fields` is provided alongside `--query`, every JMESPath
        leaf identifier missing from the set produces one stderr warning line
        — this is how silent-null projections (a leaf the GraphQL query never
        selected) become visible. Set `MONDO_NO_PROJECTION_WARNINGS=1` to
        suppress.
        """
        out = stream or sys.stdout
        is_tty = (
            default_tty_override
            if default_tty_override is not None
            else hasattr(out, "isatty") and out.isatty()
        )
        from mondo.output import choose_default_format, format_output
        from mondo.output.query import apply_query

        fmt = self.output or choose_default_format(is_tty=is_tty)
        projected = apply_query(data, self.query)
        if (
            self.query
            and selected_fields is not None
            and os.environ.get("MONDO_NO_PROJECTION_WARNINGS") != "1"
        ):
            self._warn_unselected_projection_fields(self.query, selected_fields)
        format_output(projected, fmt=fmt, stream=out, tty=is_tty)

    @staticmethod
    def _warn_unselected_projection_fields(
        expression: str, selected_fields: frozenset[str]
    ) -> None:
        import typer

        from mondo.output.query import extract_query_leaf_fields

        leaves = extract_query_leaf_fields(expression)
        for missing in sorted(leaves - selected_fields):
            typer.secho(
                f"warning: field '{missing}' is not in the GraphQL selection set",
                fg=typer.colors.YELLOW,
                err=True,
            )

    def resolve_token(self) -> ResolvedToken:
        """Run the token resolution chain using this invocation's options."""
        from mondo.api.auth import resolve_token
        from mondo.config.loader import config_path

        cfg = self._load()
        profile = cfg.get_profile(self.profile_name)
        return resolve_token(
            profile=profile,
            flag_token=self.flag_token,
            profile_name=self.profile_name or cfg.default_profile,
            config_path=config_path(),
        )

    def build_client(self) -> MondayClient:
        """Convenience: resolve the token, pick the API version, build the client."""
        from mondo.api.auth import resolve_token
        from mondo.api.client import MondayClient
        from mondo.config.loader import config_path

        cfg = self._load()
        profile = cfg.get_profile(self.profile_name)
        resolved = resolve_token(
            profile=profile,
            flag_token=self.flag_token,
            profile_name=self.profile_name or cfg.default_profile,
            config_path=config_path(),
        )
        api_version = self.flag_api_version or profile.api_version or cfg.api_version
        return MondayClient(token=resolved.token, api_version=api_version)

    def resolve_cache_config(self) -> ResolvedCacheConfig:
        """Resolve the fully-merged cache configuration for this invocation."""
        if self._cache_config is None:
            from mondo.cache import resolve_cache_config

            self._cache_config = resolve_cache_config(
                self._load(), profile_name=self.profile_name
            )
        return self._cache_config

    def api_endpoint(self) -> str:
        """Effective monday API endpoint for the current profile.

        Used as the `api_endpoint` key for cache envelopes so switching profiles
        (e.g. to a different monday account) doesn't serve stale data.
        """
        cfg = self._load()
        profile = cfg.get_profile(self.profile_name)
        return profile.api_url

    def build_cache_store(
        self, entity_type: EntityType, *, scope: str | None = None
    ) -> CacheStore:
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
