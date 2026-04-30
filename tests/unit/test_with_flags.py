"""Tests for the Phase 2.2 `--with-*` opt-in flags.

Covers:

- The query builders / constants change shape based on the flag.
- The `_field_sets` helpers union the opt-in fields permissively so the
  Phase 2.1 warning machinery doesn't false-positive when the flag is set.
"""

from __future__ import annotations

from mondo.api.queries import (
    BOARD_GET,
    BOARD_GET_WITH_VIEWS,
    build_boards_list_query,
)
from mondo.api.selection import extract_selected_fields
from mondo.cli._field_sets import board_get_fields, board_list_fields


class TestBoardGetWithViews:
    def test_default_excludes_views(self) -> None:
        assert "views" not in extract_selected_fields(BOARD_GET)
        assert "settings_str" not in extract_selected_fields(BOARD_GET)

    def test_with_views_constant_includes_views(self) -> None:
        fields = extract_selected_fields(BOARD_GET_WITH_VIEWS)
        assert "views" in fields
        assert "settings_str" in fields

    def test_with_views_keeps_default_fields(self) -> None:
        # Adding the views fragment must NOT drop any default field.
        default = extract_selected_fields(BOARD_GET)
        with_views = extract_selected_fields(BOARD_GET_WITH_VIEWS)
        assert default <= with_views

    def test_field_set_helper_default_excludes_views(self) -> None:
        # Default-flag set still warns on `views` (since user didn't opt in).
        assert "views" not in board_get_fields()

    def test_field_set_helper_with_views_includes(self) -> None:
        # When `--with-views` is wired through, the warning machinery sees
        # `views` as selected and stays silent.
        assert "views" in board_get_fields(with_views=True)


class TestBoardListWithTags:
    def test_default_excludes_tag_color(self) -> None:
        # Without `with_tags`, the boards list query has `tags` only at the
        # default level (which is absent). Specifically `color` should not
        # appear under boards as a top-level leaf.
        query, _ = build_boards_list_query()
        assert "tags" not in extract_selected_fields(query)

    def test_with_tags_includes_tag_fields(self) -> None:
        query, _ = build_boards_list_query(with_tags=True)
        fields = extract_selected_fields(query)
        assert "tags" in fields
        assert "color" in fields
        assert "name" in fields  # tag.name (also present at board level)

    def test_with_tags_keeps_default_fields(self) -> None:
        plain, _ = build_boards_list_query()
        tagged, _ = build_boards_list_query(with_tags=True)
        assert extract_selected_fields(plain) <= extract_selected_fields(tagged)

    def test_field_set_helper_default_excludes_tags(self) -> None:
        assert "tags" not in board_list_fields()

    def test_field_set_helper_with_tags_includes(self) -> None:
        assert "tags" in board_list_fields(with_tags=True)


class TestBackwardsCompat:
    def test_default_board_get_unchanged(self) -> None:
        # Phase 2.2 refactored BOARD_GET to be built from a tuple; the
        # resulting field set must equal what was there before.
        fields = extract_selected_fields(BOARD_GET)
        # Spot-check: every leaf the previous string had must still be there.
        for required in (
            "id", "name", "description", "state", "board_kind", "type",
            "board_folder_id", "workspace_id", "hierarchy_type", "items_count",
            "updated_at", "permissions", "workspace", "owners", "subscribers",
            "top_group", "groups", "columns", "tags",
        ):
            assert required in fields, f"missing {required}"

    def test_default_boards_list_unchanged(self) -> None:
        query, _ = build_boards_list_query()
        fields = extract_selected_fields(query)
        for required in (
            "id", "name", "description", "state", "board_kind",
            "board_folder_id", "workspace_id", "workspace", "hierarchy_type",
            "created_at", "updated_at", "type",
        ):
            assert required in fields, f"missing {required}"
