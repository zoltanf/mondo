"""Pydantic models describing the `~/.config/mondo/config.yaml` shape."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OutputFormat = Literal["table", "json", "jsonc", "yaml", "tsv", "csv", "none"]


class Profile(BaseModel):
    """A named configuration profile (see plan §10)."""

    model_config = ConfigDict(extra="forbid")

    api_url: str = "https://api.monday.com/v2"
    api_token: str | None = None
    api_token_keyring: str | None = Field(
        default=None,
        description="keyring key in 'service:username' format; resolved via keyring.get_password",
    )
    api_version: str | None = None
    default_board_id: int | None = None
    default_workspace_id: int | None = None
    output: OutputFormat | None = None


class Config(BaseModel):
    """Top-level config model."""

    model_config = ConfigDict(extra="forbid")

    default_profile: str = "default"
    api_version: str = "2026-01"
    profiles: dict[str, Profile] = Field(default_factory=dict)

    def get_profile(self, name: str | None) -> Profile:
        """Return the named profile, or the default one, or an empty Profile.

        Missing-named profiles raise KeyError.
        """
        key = name or self.default_profile
        if not self.profiles:
            # First-run: no profiles configured. Return an empty one so we can
            # still pick up MONDAY_API_TOKEN from the environment.
            return Profile()
        if key not in self.profiles:
            raise KeyError(f"profile {key!r} not found; available: {sorted(self.profiles)}")
        return self.profiles[key]
