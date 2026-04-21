"""Pydantic models describing the `~/.config/mondo/config.yaml` shape."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OutputFormat = Literal["table", "json", "jsonc", "yaml", "tsv", "csv", "none"]

# Built-in cache TTL defaults (seconds). Spec §10.1.
DEFAULT_CACHE_TTL_BOARDS = 28800  # 8h
DEFAULT_CACHE_TTL_WORKSPACES = 86400  # 24h
DEFAULT_CACHE_TTL_USERS = 86400
DEFAULT_CACHE_TTL_TEAMS = 86400
DEFAULT_CACHE_TTL_COLUMNS = 1200  # 20m — per-board column definitions
DEFAULT_CACHE_TTL_DOCS = 28800  # 8h — same as boards; docs are low-churn
DEFAULT_CACHE_TTL_FOLDERS = 28800  # 8h
DEFAULT_CACHE_FUZZY_THRESHOLD = 70


class CacheTTLConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boards: int | None = None
    workspaces: int | None = None
    users: int | None = None
    teams: int | None = None
    columns: int | None = None
    docs: int | None = None
    folders: int | None = None


class CacheFuzzyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: int | None = None


class CacheConfig(BaseModel):
    """User-facing `cache:` section. All fields are optional; absent fields
    fall back to built-in defaults via `resolve_cache_config()`."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    dir: str | None = None
    ttl: CacheTTLConfig | None = None
    fuzzy: CacheFuzzyConfig | None = None


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
    cache: CacheConfig | None = None


class Config(BaseModel):
    """Top-level config model."""

    model_config = ConfigDict(extra="forbid")

    default_profile: str = "default"
    api_version: str = "2026-01"
    profiles: dict[str, Profile] = Field(default_factory=dict)
    cache: CacheConfig | None = None

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
