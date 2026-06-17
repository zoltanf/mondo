"""Tests for mondo.cli._doc_images — pure filename / markdown-rewrite helpers.

The download/resolve paths hit the network and `assets(ids)`, so they're
exercised by the live integration suite; here we cover the pure logic.
"""

from __future__ import annotations

from mondo.cli._doc_images import (
    extract_asset_ids_from_markdown,
    local_filename,
    rewrite_markdown_images,
)


class TestLocalFilename:
    def test_prefixes_asset_id_to_name(self) -> None:
        assert (
            local_filename(238776078, "image-from-clipboard.png", ".png")
            == "238776078-image-from-clipboard.png"
        )

    def test_collision_names_stay_unique_via_id(self) -> None:
        """Clipboard images share a name; the id prefix keeps them distinct."""
        a = local_filename(1, "image-from-clipboard.png", ".png")
        b = local_filename(2, "image-from-clipboard.png", ".png")
        assert a != b
        assert a == "1-image-from-clipboard.png"

    def test_falls_back_to_extension_when_no_name(self) -> None:
        assert local_filename(99, None, ".jpg") == "99-asset.jpg"

    def test_no_name_no_extension(self) -> None:
        assert local_filename(99, None, None) == "99-asset"

    def test_sanitizes_unsafe_characters(self) -> None:
        assert local_filename(5, "a b/c?.png", ".png") == "5-a-b-c-.png"


class TestExtractAssetIds:
    def test_extracts_protected_static_ids(self) -> None:
        md = (
            "![Image: ](https://acme.monday.com/protected_static/1/"
            "resources/238776078/image-from-clipboard.png)"
        )
        assert extract_asset_ids_from_markdown(md) == [238776078]

    def test_ignores_external_images(self) -> None:
        md = "![a](https://example.test/img.png)"
        assert extract_asset_ids_from_markdown(md) == []

    def test_dedupes_preserving_order(self) -> None:
        md = (
            "![](https://x/resources/20/a.png) "
            "![](https://x/resources/10/b.png) "
            "![](https://x/resources/20/a.png)"
        )
        assert extract_asset_ids_from_markdown(md) == [20, 10]

    def test_finds_images_inside_table_cells(self) -> None:
        md = (
            "| ![](https://x/resources/110/a.png) "
            "| ![](https://x/resources/117/b.png) |"
        )
        assert extract_asset_ids_from_markdown(md) == [110, 117]


class TestRewriteMarkdownImages:
    def test_rewrites_mapped_id_keeps_alt(self) -> None:
        md = "![Image: ](https://x/resources/55/foo.png)"
        assert (
            rewrite_markdown_images(md, {55: "55-foo.png"})
            == "![Image: ](55-foo.png)"
        )

    def test_unmapped_id_keeps_url(self) -> None:
        md = "![](https://x/resources/55/foo.png)"
        assert rewrite_markdown_images(md, {}) == md

    def test_external_image_untouched(self) -> None:
        md = "![](https://example.test/img.png)"
        assert rewrite_markdown_images(md, {1: "x.png"}) == md
