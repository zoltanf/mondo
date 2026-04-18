"""Token resolution chain.

Precedence (per plan §10):
    1. `--api-token` flag
    2. `MONDAY_API_TOKEN` env var
    3. Profile's `api_token_keyring` (via the OS keyring)
    4. Profile's `api_token` (from config.yaml — last resort)
    5. Fail with a pointer to `mondo auth login`
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import keyring

from mondo.api.errors import AuthError
from mondo.config.schema import Profile

ENV_VAR = "MONDAY_API_TOKEN"


class TokenSource(StrEnum):
    FLAG = "flag"
    ENV = "env"
    KEYRING = "keyring"
    PROFILE_FILE = "profile_file"

    def describe(self) -> str:
        return {
            TokenSource.FLAG: "--api-token flag",
            TokenSource.ENV: f"{ENV_VAR} environment variable",
            TokenSource.KEYRING: "OS keyring",
            TokenSource.PROFILE_FILE: "profile file (config.yaml)",
        }[self]


@dataclass(frozen=True)
class ResolvedToken:
    token: str
    source: TokenSource
    profile_name: str | None = None
    config_path: Path | None = None
    keyring_key: str | None = None


def _parse_keyring_key(key: str) -> tuple[str, str]:
    """Split 'service:username' into its parts. Raises AuthError on bad format."""
    if ":" not in key:
        raise AuthError(f"invalid api_token_keyring {key!r}: expected 'service:username' format")
    service, _, username = key.partition(":")
    if not service or not username:
        raise AuthError(f"invalid api_token_keyring {key!r}: expected 'service:username' format")
    return service, username


def resolve_token(
    *,
    profile: Profile,
    flag_token: str | None,
    profile_name: str | None = None,
    config_path: Path | None = None,
) -> ResolvedToken:
    """Run the precedence chain and return the first hit. Raises AuthError on miss."""
    if flag_token:
        return ResolvedToken(
            token=flag_token,
            source=TokenSource.FLAG,
            profile_name=profile_name,
            config_path=config_path,
        )

    env_token = os.environ.get(ENV_VAR)
    if env_token:
        return ResolvedToken(
            token=env_token,
            source=TokenSource.ENV,
            profile_name=profile_name,
            config_path=config_path,
        )

    if profile.api_token_keyring:
        service, username = _parse_keyring_key(profile.api_token_keyring)
        stored = keyring.get_password(service, username)
        if stored:
            return ResolvedToken(
                token=stored,
                source=TokenSource.KEYRING,
                profile_name=profile_name,
                config_path=config_path,
                keyring_key=profile.api_token_keyring,
            )

    if profile.api_token:
        return ResolvedToken(
            token=profile.api_token,
            source=TokenSource.PROFILE_FILE,
            profile_name=profile_name,
            config_path=config_path,
        )

    raise AuthError(
        "no API token configured. Run `mondo auth login`, set "
        f"{ENV_VAR} in your environment, or pass --api-token."
    )
