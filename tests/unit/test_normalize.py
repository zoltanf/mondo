"""Unit tests for `mondo.cli._normalize` — entry renaming that brings
board-list and doc-list entries onto a shared core shape.

The rename happens at the data layer (before filtering / emitting) so that
every downstream consumer sees `kind` and `folder_id` regardless of whether
the entry came from the live API or the cache."""

from __future__ import annotations

from mondo.cli._normalize import normalize_board_entry, normalize_doc_entry


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
