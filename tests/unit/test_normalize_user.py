"""Unit tests for `normalize_user` — the 2026-07 kind/status → legacy-boolean
derivation. Combinations match the runtime values verified live on the API."""

from __future__ import annotations

import pytest

from mondo.domain.users import normalize_user


@pytest.mark.parametrize(
    ("kind", "is_admin", "is_guest", "is_view_only"),
    [
        ("admin", True, False, False),
        ("member", False, False, False),
        ("guest", False, True, False),
        ("view_only", False, False, True),
    ],
)
def test_kind_derivation(kind, is_admin, is_guest, is_view_only) -> None:
    out = normalize_user({"id": "1", "kind": kind})
    assert out["is_admin"] is is_admin
    assert out["is_guest"] is is_guest
    assert out["is_view_only"] is is_view_only
    assert out["kind"] == kind  # new field preserved


@pytest.mark.parametrize(
    ("status", "enabled", "is_pending"),
    [
        ("ACTIVE", True, False),
        ("INACTIVE", False, False),
        ("PENDING", False, True),
    ],
)
def test_status_derivation(status, enabled, is_pending) -> None:
    out = normalize_user({"id": "1", "status": status})
    assert out["enabled"] is enabled
    assert out["is_pending"] is is_pending
    assert out["status"] == status  # new field preserved


def test_photo_url_thumb_derivation() -> None:
    out = normalize_user({"id": "1", "photo_url": {"thumb": "https://x/t.png"}})
    assert out["photo_thumb"] == "https://x/t.png"
    assert out["photo_url"] == {"thumb": "https://x/t.png"}


def test_partial_record_only_derives_present_fields() -> None:
    # A mutation payload that selected only `kind` must not invent status keys.
    out = normalize_user({"id": "1", "name": "A", "kind": "member"})
    assert "is_admin" in out
    assert "enabled" not in out
    assert "is_pending" not in out
    assert "photo_thumb" not in out


def test_no_new_fields_is_lossless() -> None:
    src = {"id": "1", "name": "Legacy"}
    assert normalize_user(src) == src


def test_missing_photo_thumb_key() -> None:
    out = normalize_user({"id": "1", "photo_url": {}})
    assert out["photo_thumb"] is None


def test_null_photo_url_emits_none_thumb() -> None:
    # `photo_url` selected but null → keep a stable shape, not a dropped key.
    out = normalize_user({"id": "1", "photo_url": None})
    assert "photo_thumb" in out
    assert out["photo_thumb"] is None


def test_null_kind_emits_none_booleans() -> None:
    out = normalize_user({"id": "1", "kind": None})
    assert out["is_admin"] is None
    assert out["is_guest"] is None
    assert out["is_view_only"] is None


def test_null_status_emits_none_booleans() -> None:
    out = normalize_user({"id": "1", "status": None})
    assert out["enabled"] is None
    assert out["is_pending"] is None
