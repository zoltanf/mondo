"""Tests for mondo.config — schema validation and XDG-compliant loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from mondo.config.loader import (
    DEFAULT_API_URL,
    DEFAULT_API_VERSION,
    ConfigFileNotFoundError,
    config_path,
    load_config,
)
from mondo.config.schema import Config, Profile


class TestSchema:
    def test_profile_defaults(self) -> None:
        p = Profile()
        assert p.api_url == DEFAULT_API_URL
        assert p.api_token is None
        assert p.api_token_keyring is None
        assert p.api_version is None
        assert p.default_board_id is None
        assert p.default_workspace_id is None
        assert p.output is None

    def test_profile_with_token(self) -> None:
        p = Profile(api_token="my-token")
        assert p.api_token == "my-token"

    def test_config_default_profile(self) -> None:
        cfg = Config()
        assert cfg.default_profile == "default"
        assert cfg.api_version == DEFAULT_API_VERSION
        assert cfg.profiles == {}

    def test_get_profile_returns_named(self) -> None:
        cfg = Config(
            default_profile="work",
            profiles={
                "work": Profile(api_token="w"),
                "home": Profile(api_token="h"),
            },
        )
        assert cfg.get_profile("work").api_token == "w"
        assert cfg.get_profile("home").api_token == "h"

    def test_get_profile_defaults_to_default_profile(self) -> None:
        cfg = Config(
            default_profile="work",
            profiles={"work": Profile(api_token="w")},
        )
        assert cfg.get_profile(None).api_token == "w"

    def test_get_profile_missing_raises(self) -> None:
        cfg = Config(profiles={"a": Profile()})
        with pytest.raises(KeyError, match="nope"):
            cfg.get_profile("nope")

    def test_get_profile_autocreates_empty_default(self) -> None:
        """When no profiles are defined at all, get_profile(None) returns an
        empty profile — this supports first-run with just `MONDAY_API_TOKEN`."""
        cfg = Config()
        p = cfg.get_profile(None)
        assert p.api_token is None  # no profile = empty profile


class TestConfigPath:
    def test_respects_xdg_config_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/xdg")
        assert config_path() == Path("/custom/xdg/mondo/config.yaml")

    def test_falls_back_to_home_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        assert config_path() == tmp_path / ".config" / "mondo" / "config.yaml"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        p = tmp_path / "override.yaml"
        monkeypatch.setenv("MONDO_CONFIG", str(p))
        assert config_path() == p


class TestLoadConfig:
    def test_missing_returns_empty(self, tmp_path: Path) -> None:
        # Default behavior: missing file → empty Config (not an error)
        cfg = load_config(path=tmp_path / "nope.yaml")
        assert isinstance(cfg, Config)
        assert cfg.profiles == {}

    def test_missing_strict_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigFileNotFoundError):
            load_config(path=tmp_path / "nope.yaml", strict=True)

    def test_parses_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        p.write_text(
            """
default_profile: personal
api_version: "2026-01"
profiles:
  personal:
    api_token: MY_TOKEN
    default_board_id: 1234567890
    output: table
  work:
    api_token_keyring: mondo:work
    api_version: "2025-10"
""".lstrip()
        )
        cfg = load_config(path=p)
        assert cfg.default_profile == "personal"
        assert cfg.api_version == "2026-01"
        assert cfg.profiles["personal"].api_token == "MY_TOKEN"
        assert cfg.profiles["personal"].default_board_id == 1234567890
        assert cfg.profiles["personal"].output == "table"
        assert cfg.profiles["work"].api_token_keyring == "mondo:work"
        assert cfg.profiles["work"].api_version == "2025-10"

    def test_expands_env_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_TOKEN_VAR", "resolved-token")
        p = tmp_path / "config.yaml"
        p.write_text(
            """
profiles:
  personal:
    api_token: ${TEST_TOKEN_VAR}
""".lstrip()
        )
        cfg = load_config(path=p)
        assert cfg.profiles["personal"].api_token == "resolved-token"

    def test_unknown_env_var_left_as_literal(self, tmp_path: Path) -> None:
        """An unresolved ${VAR} leaves the literal so the user sees it in errors."""
        p = tmp_path / "config.yaml"
        p.write_text(
            """
profiles:
  personal:
    api_token: ${NONEXISTENT_VAR_XYZ_789}
""".lstrip()
        )
        cfg = load_config(path=p)
        assert cfg.profiles["personal"].api_token == "${NONEXISTENT_VAR_XYZ_789}"

    def test_empty_yaml_file_returns_empty_config(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        p.write_text("")
        cfg = load_config(path=p)
        assert cfg.profiles == {}
