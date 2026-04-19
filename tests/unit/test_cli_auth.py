"""End-to-end CLI tests for `mondo auth status` and `mondo auth whoami`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from mondo.cli.main import app

ENDPOINT = "https://api.monday.com/v2"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("MONDO_PROFILE", raising=False)
    monkeypatch.delenv("MONDAY_API_VERSION", raising=False)
    monkeypatch.setenv("MONDO_CONFIG", str(tmp_path / "nope.yaml"))


def _me_response() -> dict:
    return {
        "data": {
            "me": {
                "id": "42",
                "name": "Alice",
                "email": "alice@example.com",
                "is_admin": True,
                "account": {"id": "100", "name": "Acme", "slug": "acme", "tier": "pro"},
            }
        },
        "extensions": {"request_id": "r-1"},
    }


class TestStatus:
    def test_no_token_exits_3(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MONDAY_API_TOKEN", raising=False)
        # Isolate from the dev machine's real keyring (which may have an
        # entry from `mondo auth login` during manual testing).
        monkeypatch.setattr(
            "mondo.api.auth.keyring.get_password", lambda service, username: None
        )
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 3

    def test_with_env_token_prints_identity(
        self, monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
    ) -> None:
        monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_me_response())
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0, result.stdout
        assert "Alice" in result.stdout
        assert "Acme" in result.stdout
        assert "MONDAY_API_TOKEN environment variable" in result.stdout

    def test_auth_error_from_api_exits_3(
        self, monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
    ) -> None:
        monkeypatch.setenv("MONDAY_API_TOKEN", "bad-token-abcdef-long-enough")
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            status_code=401,
            text="Unauthorized",
        )
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 3


class TestWhoami:
    def test_non_tty_emits_json(
        self, monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock
    ) -> None:
        monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_me_response())
        # CliRunner's stdout is not a TTY → default format is json
        result = runner.invoke(app, ["auth", "whoami"])
        assert result.exit_code == 0
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Alice"
        assert parsed["account"]["name"] == "Acme"

    def test_query_projection(self, monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock) -> None:
        monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_me_response())
        result = runner.invoke(app, ["-q", "name", "-o", "none", "auth", "whoami"])
        assert result.exit_code == 0
        assert result.stdout.strip() == "Alice"

    def test_output_yaml(self, monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock) -> None:
        monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_me_response())
        result = runner.invoke(app, ["-o", "yaml", "auth", "whoami"])
        assert result.exit_code == 0
        assert "name: Alice" in result.stdout
        assert "slug: acme" in result.stdout

    def test_sends_me_query(self, monkeypatch: pytest.MonkeyPatch, httpx_mock: HTTPXMock) -> None:
        monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_me_response())
        runner.invoke(app, ["auth", "whoami"])
        body = json.loads(httpx_mock.get_request().content)  # type: ignore[union-attr]
        assert "me {" in body["query"]
        assert "account" in body["query"]


class TestLoginLogout:
    def test_login_requires_tty_when_no_token_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # CliRunner's stdin is a pipe — not a TTY
        monkeypatch.delenv("MONDAY_API_TOKEN", raising=False)
        result = runner.invoke(app, ["auth", "login"])
        assert result.exit_code == 2

    def test_login_with_token_flag_stores_in_keyring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stored: dict[tuple[str, str], str] = {}

        def fake_set(service: str, username: str, password: str) -> None:
            stored[(service, username)] = password

        def fake_get(service: str, username: str) -> str | None:
            return stored.get((service, username))

        def fake_delete(service: str, username: str) -> None:
            stored.pop((service, username), None)

        import keyring as kr

        monkeypatch.setattr(kr, "set_password", fake_set)
        monkeypatch.setattr(kr, "get_password", fake_get)
        monkeypatch.setattr(kr, "delete_password", fake_delete)

        result = runner.invoke(app, ["auth", "login", "--token", "new-token-abcdef-long-enough"])
        assert result.exit_code == 0
        assert ("mondo", "default") in stored
        assert stored[("mondo", "default")] == "new-token-abcdef-long-enough"

        # logout removes it
        result = runner.invoke(app, ["auth", "logout"])
        assert result.exit_code == 0
        assert ("mondo", "default") not in stored

        # logout again is a no-op (not an error)
        result = runner.invoke(app, ["auth", "logout"])
        assert result.exit_code == 0
