"""Unit tests for `mondo.cli._normalize` — entry renaming that brings
board-list and doc-list entries onto a shared core shape.

The rename happens at the data layer (before filtering / emitting) so that
every downstream consumer sees `kind` and `folder_id` regardless of whether
the entry came from the live API or the cache."""

from __future__ import annotations

from mondo.cli._normalize import normalize_board_entry, normalize_doc_entry, normalize_folder_entry


class TestNormalizeBoard:
    def test_renames_board_kind_to_kind(self) -> None:
        out = normalize_board_entry({"id": "1", "board_kind": "public"})
        assert out["kind"] == "public"
        assert "board_kind" not in out

    def test_renames_board_folder_id_to_folder_id(self) -> None:
        out = normalize_board_entry({"id": "1", "board_folder_id": "42"})
        assert out["folder_id"] == "42"
        assert "board_folder_id" not in out

    def test_passes_through_other_keys(self) -> None:
        out = normalize_board_entry(
            {"id": "1", "name": "X", "state": "active", "board_kind": "private"}
        )
        assert out["id"] == "1"
        assert out["name"] == "X"
        assert out["state"] == "active"
        assert out["kind"] == "private"

    def test_no_board_kind_no_crash(self) -> None:
        out = normalize_board_entry({"id": "1"})
        assert out == {"id": "1"}

    def test_does_not_mutate_input(self) -> None:
        src = {"id": "1", "board_kind": "public", "board_folder_id": "9"}
        normalize_board_entry(src)
        assert src == {"id": "1", "board_kind": "public", "board_folder_id": "9"}

    def test_null_folder_id_passes_through(self) -> None:
        out = normalize_board_entry({"id": "1", "board_folder_id": None})
        assert out["folder_id"] is None

    def test_workspace_pair_stays_adjacent(self) -> None:
        out = normalize_board_entry(
            {
                "id": "1",
                "workspace_id": "42",
                "name": "X",
                "workspace_name": "Engineering",
                "state": "active",
            }
        )
        keys = list(out.keys())
        assert keys[keys.index("workspace_id") + 1] == "workspace_name"

    def test_created_and_updated_move_to_tail(self) -> None:
        out = normalize_board_entry(
            {
                "id": "1",
                "created_at": "2024-01-01",
                "name": "X",
                "updated_at": "2024-01-02",
            }
        )
        assert list(out.keys())[-2:] == ["created_at", "updated_at"]


class TestNormalizeDoc:
    def test_renames_doc_kind_to_kind(self) -> None:
        out = normalize_doc_entry({"id": "1", "doc_kind": "public"})
        assert out["kind"] == "public"
        assert "doc_kind" not in out

    def test_renames_doc_folder_id_to_folder_id(self) -> None:
        out = normalize_doc_entry({"id": "1", "doc_folder_id": "42"})
        assert out["folder_id"] == "42"
        assert "doc_folder_id" not in out

    def test_passes_through_other_keys(self) -> None:
        out = normalize_doc_entry(
            {
                "id": "1",
                "object_id": "100",
                "name": "Spec",
                "doc_kind": "private",
                "url": "https://example.com/1",
            }
        )
        assert out["id"] == "1"
        assert out["object_id"] == "100"
        assert out["name"] == "Spec"
        assert out["kind"] == "private"
        assert out["url"] == "https://example.com/1"

    def test_no_doc_kind_no_crash(self) -> None:
        out = normalize_doc_entry({"id": "1"})
        assert out == {"id": "1"}

    def test_does_not_mutate_input(self) -> None:
        src = {"id": "1", "doc_kind": "public", "doc_folder_id": "9"}
        normalize_doc_entry(src)
        assert src == {"id": "1", "doc_kind": "public", "doc_folder_id": "9"}

    def test_null_folder_id_passes_through(self) -> None:
        out = normalize_doc_entry({"id": "1", "doc_folder_id": None})
        assert out["folder_id"] is None

    def test_workspace_pair_stays_adjacent(self) -> None:
        out = normalize_doc_entry(
            {
                "id": "1",
                "workspace_id": "42",
                "name": "Spec",
                "workspace_name": "Engineering",
                "doc_kind": "private",
            }
        )
        keys = list(out.keys())
        assert keys[keys.index("workspace_id") + 1] == "workspace_name"

    def test_created_and_updated_move_to_tail(self) -> None:
        out = normalize_doc_entry(
            {
                "id": "1",
                "updated_at": "2024-01-02",
                "name": "Spec",
                "created_at": "2024-01-01",
            }
        )
        assert list(out.keys())[-2:] == ["created_at", "updated_at"]


class TestNormalizeFolder:
    def test_both_workspace_and_parent_populated(self) -> None:
        entry = {
            "id": "10",
            "name": "My Folder",
            "color": "blue",
            "created_at": "2024-01-01T00:00:00Z",
            "owner_id": "99",
            "workspace": {"id": "5", "name": "Main"},
            "parent": {"id": "3", "name": "Parent Folder"},
        }
        out = normalize_folder_entry(entry)
        assert out["id"] == "10"
        assert out["name"] == "My Folder"
        assert out["color"] == "blue"
        assert out["created_at"] == "2024-01-01T00:00:00Z"
        assert out["owner_id"] == "99"
        assert out["workspace_id"] == "5"
        assert out["workspace_name"] == "Main"
        assert out["parent_id"] == "3"
        assert out["parent_name"] == "Parent Folder"
        assert "workspace" not in out
        assert "parent" not in out

    def test_parent_none_root_folder(self) -> None:
        entry = {
            "id": "10",
            "name": "Root",
            "color": None,
            "created_at": "2024-01-01T00:00:00Z",
            "owner_id": "99",
            "workspace": {"id": "5", "name": "Main"},
            "parent": None,
        }
        out = normalize_folder_entry(entry)
        assert out["parent_id"] is None
        assert out["parent_name"] is None
        assert out["workspace_id"] == "5"

    def test_workspace_none_main_workspace(self) -> None:
        entry = {
            "id": "10",
            "name": "Folder",
            "color": None,
            "created_at": "2024-01-01T00:00:00Z",
            "owner_id": "99",
            "workspace": None,
            "parent": {"id": "3", "name": "Parent"},
        }
        out = normalize_folder_entry(entry)
        assert out["workspace_id"] is None
        assert out["workspace_name"] is None
        assert out["parent_id"] == "3"

    def test_both_none(self) -> None:
        entry = {
            "id": "10",
            "name": "Orphan",
            "color": None,
            "created_at": "2024-01-01T00:00:00Z",
            "owner_id": None,
            "workspace": None,
            "parent": None,
        }
        out = normalize_folder_entry(entry)
        assert out["workspace_id"] is None
        assert out["workspace_name"] is None
        assert out["parent_id"] is None
        assert out["parent_name"] is None

    def test_does_not_mutate_input(self) -> None:
        entry = {
            "id": "10",
            "name": "Folder",
            "color": "red",
            "created_at": "2024-01-01T00:00:00Z",
            "owner_id": "1",
            "workspace": {"id": "5", "name": "Main"},
            "parent": None,
        }
        original = dict(entry)
        normalize_folder_entry(entry)
        assert entry == original

    def test_output_key_order(self) -> None:
        entry = {
            "id": "10",
            "name": "Folder",
            "color": "green",
            "created_at": "2024-01-01T00:00:00Z",
            "owner_id": "7",
            "workspace": {"id": "5", "name": "WS"},
            "parent": {"id": "3", "name": "P"},
        }
        out = normalize_folder_entry(entry)
        assert list(out.keys()) == [
            "id",
            "name",
            "color",
            "workspace_id",
            "workspace_name",
            "parent_id",
            "parent_name",
            "owner_id",
            "created_at",
        ]
