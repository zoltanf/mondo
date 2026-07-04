"""Token/client construction for the CLI layer.

Extracted from ``GlobalOpts.resolve_token`` / ``build_client`` /
``api_endpoint`` so client construction is a set of free functions taking an
already-loaded :class:`Config` plus the invocation's flags. ``GlobalOpts``
keeps thin wrappers that ``self._load()`` and forward, so call sites are
unchanged. ``build_client_from_config`` reuses ``resolve_token_from_config``
instead of duplicating the resolution call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mondo.api.auth import ResolvedToken
    from mondo.api.client import MondayClient
    from mondo.config.schema import Config


def resolve_token_from_config(
    cfg: Config, *, profile_name: str | None, flag_token: str | None
) -> ResolvedToken:
    """Run the token resolution chain for the given profile/flag token."""
    from mondo.api.auth import resolve_token
    from mondo.config.loader import config_path

    profile = cfg.get_profile(profile_name)
    return resolve_token(
        profile=profile,
        flag_token=flag_token,
        profile_name=profile_name or cfg.default_profile,
        config_path=config_path(),
    )


def build_client_from_config(
    cfg: Config,
    *,
    profile_name: str | None,
    flag_token: str | None,
    flag_api_version: str | None,
) -> MondayClient:
    """Resolve the token, pick the API version, build the client."""
    from mondo.api.client import MondayClient

    profile = cfg.get_profile(profile_name)
    resolved = resolve_token_from_config(
        cfg, profile_name=profile_name, flag_token=flag_token
    )
    api_version = flag_api_version or profile.api_version or cfg.api_version
    return MondayClient(token=resolved.token, api_version=api_version)


def api_endpoint_from_config(cfg: Config, *, profile_name: str | None) -> str:
    """Effective monday API endpoint for the given profile."""
    profile = cfg.get_profile(profile_name)
    return profile.api_url
