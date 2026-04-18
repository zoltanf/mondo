"""GlobalOpts — the typed context object attached to every Typer command.

A command reads it via `ctx.obj: GlobalOpts = ctx.ensure_object(GlobalOpts)`
or uses the helper `build_client(opts)` to get a ready-to-use MondayClient.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, TextIO

from mondo.api.auth import ResolvedToken, resolve_token
from mondo.api.client import MondayClient
from mondo.config.loader import config_path, load_config
from mondo.output import choose_default_format, format_output
from mondo.output.query import apply_query


@dataclass
class GlobalOpts:
    """Carries parsed global options from the root Typer callback."""

    profile_name: str | None
    flag_token: str | None
    flag_api_version: str | None
    verbose: bool
    debug: bool
    output: str | None = None
    query: str | None = None
    yes: bool = False
    dry_run: bool = False

    def emit(
        self,
        data: Any,
        *,
        stream: TextIO | None = None,
        default_tty_override: bool | None = None,
    ) -> None:
        """Render `data` to stdout (or `stream`) honoring --output and --query.

        Applies `--query` before formatting. Auto-picks the format based on
        whether stdout is a TTY if `--output` wasn't set.
        """
        out = stream or sys.stdout
        is_tty = (
            default_tty_override
            if default_tty_override is not None
            else hasattr(out, "isatty") and out.isatty()
        )
        fmt = self.output or choose_default_format(is_tty=is_tty)
        projected = apply_query(data, self.query)
        format_output(projected, fmt=fmt, stream=out, tty=is_tty)

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
