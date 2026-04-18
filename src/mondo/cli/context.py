"""GlobalOpts — the typed context object attached to every Typer command.

A command reads it via `ctx.obj: GlobalOpts = ctx.ensure_object(GlobalOpts)`
or uses the helper `build_client(opts)` to get a ready-to-use MondayClient.
"""

from __future__ import annotations

from dataclasses import dataclass

from mondo.api.auth import ResolvedToken, resolve_token
from mondo.api.client import MondayClient
from mondo.config.loader import config_path, load_config


@dataclass
class GlobalOpts:
    """Carries parsed global options from the root Typer callback."""

    profile_name: str | None
    flag_token: str | None
    flag_api_version: str | None
    verbose: bool
    debug: bool

    def resolve_token(self) -> ResolvedToken:
        """Run the token resolution chain using this invocation's options."""
        cfg = load_config()
        profile = cfg.get_profile(self.profile_name)
        return resolve_token(
            profile=profile,
            flag_token=self.flag_token,
            profile_name=self.profile_name or cfg.default_profile,
            config_path=config_path(),
        )

    def build_client(self) -> MondayClient:
        """Convenience: resolve the token, pick the API version, build the client."""
        cfg = load_config()
        profile = cfg.get_profile(self.profile_name)
        resolved = resolve_token(
            profile=profile,
            flag_token=self.flag_token,
            profile_name=self.profile_name or cfg.default_profile,
            config_path=config_path(),
        )
        api_version = self.flag_api_version or profile.api_version or cfg.api_version
        return MondayClient(token=resolved.token, api_version=api_version)
