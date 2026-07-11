"""End-to-end CLI tests for `mondo user ...` (Phase 3a)."""

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
    monkeypatch.setenv("MONDAY_API_TOKEN", "env-token-abcdef-long-enough")
    monkeypatch.setenv("MONDO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MONDO_CACHE_ENABLED", "false")


def _ok(data: dict) -> dict:
    return {"data": data, "extensions": {"request_id": "r"}}


def _last_body(httpx_mock: HTTPXMock) -> dict:
    return json.loads(httpx_mock.get_requests()[-1].content)


# --- list ---


class TestList:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "users": [
                        {"id": "1", "name": "Alice", "email": "a@x.com"},
                        {"id": "2", "name": "Bob", "email": "b@x.com"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["user", "list"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [u["name"] for u in parsed] == ["Alice", "Bob"]

    def test_filters_passed_through(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"users": []}))
        result = runner.invoke(
            app,
            [
                "user",
                "list",
                "--email",
                "a@x.com",
                "--email",
                "b@x.com",
                "--name",
                "Ali",
                "--non-active",
                "--newest-first",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["emails"] == ["a@x.com", "b@x.com"]
        assert v["name"] == "Ali"
        # --non-active → status: [ACTIVE, INACTIVE] — the flag *includes*
        # deactivated users alongside active ones, matching the cache path.
        assert v["status"] == ["ACTIVE", "INACTIVE"]
        # --newest-first → sort by created_at DESC.
        assert v["sort"] == [{"field": "CREATED_AT", "direction": "DESC"}]

    def test_default_status_is_active(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"users": []}))
        result = runner.invoke(app, ["user", "list"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["status"] == ["ACTIVE"]
        assert v["userKind"] is None
        assert v["sort"] is None

    def test_kind_guests_maps_to_server_user_kind(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"users": []}))
        result = runner.invoke(app, ["user", "list", "--kind", "guests"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v["userKind"] == {"in": ["GUEST"]}

    def test_kind_guests_also_filters_client_side(self, httpx_mock: HTTPXMock) -> None:
        # Belt-and-suspenders: even if the server `user_kind {in: [GUEST]}`
        # filter regresses to a no-op (like its `not_in` sibling), guests are
        # re-filtered client-side so live and cache paths agree.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "users": [
                        {"id": "1", "name": "Member", "kind": "member", "status": "ACTIVE"},
                        {"id": "2", "name": "Guesty", "kind": "guest", "status": "ACTIVE"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["user", "list", "--kind", "guests"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [u["name"] for u in parsed] == ["Guesty"]

    def test_kind_guests_max_items_slices_after_client_filter(self, httpx_mock: HTTPXMock) -> None:
        # --max-items must not truncate the fetch before the client-side guest
        # filter runs: with a regressed server filter returning [member, guest],
        # --max-items 1 has to yield the guest, not an empty list.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "users": [
                        {"id": "1", "name": "Member", "kind": "member", "status": "ACTIVE"},
                        {"id": "2", "name": "Guesty", "kind": "guest", "status": "ACTIVE"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["user", "list", "--kind", "guests", "--max-items", "1"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [u["name"] for u in parsed] == ["Guesty"]

    def test_kind_non_guests_filters_client_side(self, httpx_mock: HTTPXMock) -> None:
        # `not_in` is a server-side no-op on 2026-07, so non_guests drops
        # guests client-side from the derived `is_guest` boolean.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "users": [
                        {"id": "1", "name": "Member", "kind": "member", "status": "ACTIVE"},
                        {"id": "2", "name": "Guesty", "kind": "guest", "status": "ACTIVE"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["user", "list", "--kind", "non_guests"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert [u["name"] for u in parsed] == ["Member"]
        # No server-side user_kind filter is sent for non_guests.
        assert _last_body(httpx_mock)["variables"]["userKind"] is None

    def test_kind_non_pending_with_include_deactivated_live(self, httpx_mock: HTTPXMock) -> None:
        # `--include-deactivated` sends status: [ACTIVE, INACTIVE] (monday's
        # INACTIVE bucket also surfaces PENDING). `--kind non_pending` then
        # drops PENDING client-side, leaving the inactive row.
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "users": [
                        {"id": "1", "name": "Inactive", "kind": "member", "status": "INACTIVE"},
                        {"id": "2", "name": "Pending", "kind": "member", "status": "PENDING"},
                    ]
                }
            ),
        )
        result = runner.invoke(
            app, ["user", "list", "--kind", "non_pending", "--include-deactivated"]
        )
        assert result.exit_code == 0, result.stdout
        # Exact status variable sent to the server.
        assert _last_body(httpx_mock)["variables"]["status"] == ["ACTIVE", "INACTIVE"]
        parsed = json.loads(result.stdout)
        assert [u["name"] for u in parsed] == ["Inactive"]

    def test_kind_non_pending_with_include_deactivated_cache(
        self, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Same scenario through the cache path: the directory fetch primes with
        # status: [ACTIVE, INACTIVE], the cache keeps everyone when the flag is
        # set, and `non_pending` drops PENDING client-side — identical result to
        # the live path, so cache/live agreement is regression-tested.
        monkeypatch.setenv("MONDO_CACHE_ENABLED", "true")
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "users": [
                        {"id": "1", "name": "Inactive", "kind": "member", "status": "INACTIVE"},
                        {"id": "2", "name": "Pending", "kind": "member", "status": "PENDING"},
                    ]
                }
            ),
        )
        result = runner.invoke(
            app, ["user", "list", "--kind", "non_pending", "--include-deactivated"]
        )
        assert result.exit_code == 0, result.stdout
        # The directory cache primes with status: [ACTIVE, INACTIVE].
        assert _last_body(httpx_mock)["variables"]["status"] == ["ACTIVE", "INACTIVE"]
        parsed = json.loads(result.stdout)
        assert [u["name"] for u in parsed] == ["Inactive"]

    def test_derives_legacy_booleans(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "users": [
                        {"id": "1", "name": "Adm", "kind": "admin", "status": "ACTIVE"},
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["user", "list"])
        assert result.exit_code == 0, result.stdout
        u = json.loads(result.stdout)[0]
        assert u["kind"] == "admin"
        assert u["status"] == "ACTIVE"
        assert u["is_admin"] is True
        assert u["is_guest"] is False
        assert u["is_view_only"] is False
        assert u["enabled"] is True
        assert u["is_pending"] is False

    def test_dry_run(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["--dry-run", "user", "list"])
        assert result.exit_code == 0, result.stdout
        assert "users" in result.stdout
        assert httpx_mock.get_requests() == []


# --- get ---


class TestGet:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok({"users": [{"id": "42", "name": "Alice", "email": "a@x.com"}]}),
        )
        result = runner.invoke(app, ["user", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "Alice"
        v = _last_body(httpx_mock)["variables"]
        assert v == {"ids": [42]}

    def test_missing_exits_6(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=ENDPOINT, method="POST", json=_ok({"users": []}))
        result = runner.invoke(app, ["user", "get", "--id", "999"])
        assert result.exit_code == 6

    def test_derives_photo_thumb_and_booleans(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "users": [
                        {
                            "id": "42",
                            "name": "Vera",
                            "kind": "view_only",
                            "status": "PENDING",
                            "photo_url": {"thumb": "https://x/thumb.png"},
                        }
                    ]
                }
            ),
        )
        result = runner.invoke(app, ["user", "get", "--id", "42"])
        assert result.exit_code == 0, result.stdout
        u = json.loads(result.stdout)
        assert u["is_view_only"] is True
        assert u["is_admin"] is False
        assert u["is_pending"] is True
        assert u["enabled"] is False
        assert u["photo_thumb"] == "https://x/thumb.png"


# --- deactivate / activate ---


class TestDeactivate:
    def test_requires_confirmation(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(app, ["user", "deactivate", "--user", "1"], input="n\n")
        assert result.exit_code == 1
        assert httpx_mock.get_requests() == []

    def test_yes_multiple_users(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "deactivate_users": {
                        "deactivated_users": [{"id": "1", "name": "A", "status": "INACTIVE"}],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["--yes", "user", "deactivate", "--user", "1", "--user", "2"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"ids": [1, 2]}
        # `status` from the response is normalized back into `enabled`.
        parsed = json.loads(result.stdout)
        assert parsed["deactivated_users"][0]["enabled"] is False


class TestActivate:
    def test_basic(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "activate_users": {
                        "activated_users": [{"id": "1", "name": "A", "status": "ACTIVE"}],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(app, ["user", "activate", "--user", "1"])
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"ids": [1]}
        parsed = json.loads(result.stdout)
        assert parsed["activated_users"][0]["enabled"] is True


# --- update-role ---


class TestUpdateRole:
    def test_admin_routes_to_admins_mutation(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "update_multiple_users_as_admins": {
                        "updated_users": [{"id": "1", "name": "A", "kind": "admin"}],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["user", "update-role", "--user", "1", "--role", "admin"],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "update_multiple_users_as_admins" in body["query"]
        # `kind` from the response is normalized back into `is_admin`.
        parsed = json.loads(result.stdout)
        assert parsed["updated_users"][0]["is_admin"] is True

    def test_member(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "update_multiple_users_as_members": {
                        "updated_users": [],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["user", "update-role", "--user", "1", "--role", "member"],
        )
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "update_multiple_users_as_members" in body["query"]

    def test_guest(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "update_multiple_users_as_guests": {
                        "updated_users": [],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(app, ["user", "update-role", "--user", "1", "--role", "guest"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "update_multiple_users_as_guests" in body["query"]

    def test_viewer(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "update_multiple_users_as_viewers": {
                        "updated_users": [],
                        "errors": [],
                    }
                }
            ),
        )
        result = runner.invoke(app, ["user", "update-role", "--user", "1", "--role", "viewer"])
        assert result.exit_code == 0, result.stdout
        body = _last_body(httpx_mock)
        assert "update_multiple_users_as_viewers" in body["query"]

    def test_invalid_role_exit_2(self, httpx_mock: HTTPXMock) -> None:
        result = runner.invoke(
            app,
            ["user", "update-role", "--user", "1", "--role", "owner"],
        )
        assert result.exit_code == 2
        assert httpx_mock.get_requests() == []


# --- team membership ---


class TestTeamMembership:
    def test_add_to_team(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "add_users_to_team": {
                        "successful_users": [{"id": "1"}, {"id": "2"}],
                        "failed_users": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            [
                "user",
                "add-to-team",
                "--team",
                "7",
                "--user",
                "1",
                "--user",
                "2",
            ],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"team": 7, "users": [1, 2]}

    def test_remove_from_team(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=ENDPOINT,
            method="POST",
            json=_ok(
                {
                    "remove_users_from_team": {
                        "successful_users": [{"id": "1"}],
                        "failed_users": [],
                    }
                }
            ),
        )
        result = runner.invoke(
            app,
            ["user", "remove-from-team", "--team", "7", "--user", "1"],
        )
        assert result.exit_code == 0, result.stdout
        v = _last_body(httpx_mock)["variables"]
        assert v == {"team": 7, "users": [1]}
