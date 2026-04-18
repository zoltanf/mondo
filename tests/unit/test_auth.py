"""Tests for mondo.api.auth — token resolution precedence."""

from __future__ import annotations

from pathlib import Path

import pytest

from mondo.api.auth import TokenSource, resolve_token
from mondo.api.errors import AuthError
from mondo.config.schema import Profile


class FakeKeyring:
    """Monkey-patched keyring backend for deterministic tests."""

    def __init__(self, store: dict[tuple[str, str], str] | None = None) -> None:
        self.store = store or {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))


@pytest.fixture
def no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONDAY_API_TOKEN", raising=False)


@pytest.fixture
def empty_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    fake = FakeKeyring()
    monkeypatch.setattr("mondo.api.auth.keyring", fake)
    return fake


class TestResolveTokenPrecedence:
    """plan §10: --api-token → MONDAY_API_TOKEN env → keyring → profile.api_token → fail."""

    def test_flag_wins_over_everything(
        self, monkeypatch: pytest.MonkeyPatch, empty_keyring: FakeKeyring
    ) -> None:
        monkeypatch.setenv("MONDAY_API_TOKEN", "env-token")
        profile = Profile(api_token="profile-token")
        result = resolve_token(profile=profile, flag_token="flag-token")
        assert result.token == "flag-token"
        assert result.source == TokenSource.FLAG

    def test_env_wins_over_profile(
        self, monkeypatch: pytest.MonkeyPatch, empty_keyring: FakeKeyring
    ) -> None:
        monkeypatch.setenv("MONDAY_API_TOKEN", "env-token")
        profile = Profile(api_token="profile-token")
        result = resolve_token(profile=profile, flag_token=None)
        assert result.token == "env-token"
        assert result.source == TokenSource.ENV

    def test_keyring_wins_over_profile_file(
        self, monkeypatch: pytest.MonkeyPatch, no_env: None
    ) -> None:
        fake = FakeKeyring({("mondo", "work"): "keyring-token"})
        monkeypatch.setattr("mondo.api.auth.keyring", fake)
        profile = Profile(
            api_token="profile-token",
            api_token_keyring="mondo:work",
        )
        result = resolve_token(profile=profile, flag_token=None)
        assert result.token == "keyring-token"
        assert result.source == TokenSource.KEYRING

    def test_profile_file_token_last_resort(self, no_env: None, empty_keyring: FakeKeyring) -> None:
        profile = Profile(api_token="profile-token")
        result = resolve_token(profile=profile, flag_token=None)
        assert result.token == "profile-token"
        assert result.source == TokenSource.PROFILE_FILE

    def test_no_token_raises(self, no_env: None, empty_keyring: FakeKeyring) -> None:
        profile = Profile()
        with pytest.raises(AuthError, match="no API token"):
            resolve_token(profile=profile, flag_token=None)

    def test_invalid_keyring_format_raises(self, no_env: None, empty_keyring: FakeKeyring) -> None:
        profile = Profile(api_token_keyring="no-colon-separator")
        with pytest.raises(AuthError, match="service:username"):
            resolve_token(profile=profile, flag_token=None)

    def test_keyring_miss_falls_back_to_profile_token(
        self, monkeypatch: pytest.MonkeyPatch, no_env: None
    ) -> None:
        """Keyring returning None should fall back to the profile file token."""
        fake = FakeKeyring()  # empty store
        monkeypatch.setattr("mondo.api.auth.keyring", fake)
        profile = Profile(
            api_token="file-token",
            api_token_keyring="mondo:absent",
        )
        result = resolve_token(profile=profile, flag_token=None)
        assert result.token == "file-token"
        assert result.source == TokenSource.PROFILE_FILE

    def test_empty_flag_treated_as_unset(
        self, monkeypatch: pytest.MonkeyPatch, empty_keyring: FakeKeyring
    ) -> None:
        monkeypatch.setenv("MONDAY_API_TOKEN", "env-token")
        result = resolve_token(profile=Profile(), flag_token="")
        assert result.source == TokenSource.ENV


class TestTokenSourceDescribe:
    """Used by `mondo auth status` to explain where the token came from."""

    def test_has_describe_for_all_sources(self) -> None:
        for src in TokenSource:
            assert isinstance(src.describe(), str)
            assert len(src.describe()) > 0


class TestResolvedTokenConfigPath:
    """Path info exposed for `mondo auth status`."""

    def test_profile_file_exposes_config_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        no_env: None,
        empty_keyring: FakeKeyring,
        tmp_path: Path,
    ) -> None:
        # resolve_token accepts an optional profile_name + config_path for display
        profile = Profile(api_token="file-token")
        config_file = tmp_path / "config.yaml"
        result = resolve_token(
            profile=profile,
            flag_token=None,
            profile_name="work",
            config_path=config_file,
        )
        assert result.profile_name == "work"
        assert result.config_path == config_file
