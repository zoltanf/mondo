"""Download monday doc images into a local folder for markdown export.

Shared by `doc get --format markdown --out` (block-tree path) and
`doc export-markdown --out` (server-rendered-string path).

monday image blocks carry a numeric `assetId` plus a protected_static `url`
that only resolves in a logged-in browser. We resolve each asset to its
pre-signed `public_url` via `assets(ids)` (reusing `ASSETS_GET`, the same
query `mondo file download` uses) and stream the bytes to disk with the
`httpx.stream(..., follow_redirects=True)` pattern from `mondo.cli.file`.

Files are named `<assetId>-<sanitized-name>` so clipboard images — which all
share the name `image-from-clipboard.png` — don't collide.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx

from mondo.api.errors import NetworkError
from mondo.api.queries import ASSETS_GET
from mondo.cli._exec import execute_read
from mondo.cli.context import GlobalOpts
from mondo.docs import collect_image_asset_ids

# assetId embedded in a monday protected_static URL: `.../resources/<id>/...`.
_RESOURCE_ID_RE = re.compile(r"/resources/(\d+)/")
# Markdown image: `![alt](url)`. URL stops at whitespace or the closing paren.
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
# Characters we keep in a local filename; everything else collapses to `-`.
_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def local_filename(asset_id: int, name: str | None, file_extension: str | None) -> str:
    """`<assetId>-<sanitized-name>` — unique even when names repeat.

    Falls back to the asset's `file_extension` when monday returns no name.
    """
    safe = _FILENAME_UNSAFE_RE.sub("-", name).strip("-") if name else f"asset{file_extension or ''}"
    return f"{asset_id}-{safe}" if safe else str(asset_id)


def extract_asset_ids_from_markdown(markdown: str) -> list[int]:
    """Asset IDs of monday-hosted images in a markdown string, de-duplicated.

    Only matches images whose URL is a monday protected_static link
    (`.../resources/<id>/...`); external image URLs are left untouched.
    """
    ids: list[int] = []
    for match in _MD_IMAGE_RE.finditer(markdown):
        rid = _RESOURCE_ID_RE.search(match.group(2))
        if rid:
            ids.append(int(rid.group(1)))
    return list(dict.fromkeys(ids))


def rewrite_markdown_images(markdown: str, filenames: dict[int, str]) -> str:
    """Rewrite monday image URLs to the local filenames in `filenames`.

    Images whose assetId isn't in the map (external, or failed to download)
    keep their original URL.
    """

    def repl(match: re.Match[str]) -> str:
        rid = _RESOURCE_ID_RE.search(match.group(2))
        if rid:
            local = filenames.get(int(rid.group(1)))
            if local is not None:
                return f"![{match.group(1)}]({local})"
        return match.group(0)

    return _MD_IMAGE_RE.sub(repl, markdown)


def _resolve_assets(opts: GlobalOpts, asset_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Key an `assets(ids)` payload by asset id. Unknown ids are simply
    absent from the result (callers fall back to the remote URL)."""
    if not asset_ids:
        return {}
    data = execute_read(opts, ASSETS_GET, {"ids": asset_ids})
    assets = data.get("assets") or []
    return {int(a["id"]): a for a in assets if a.get("id") is not None}


def _download(url: str, target: Path) -> None:
    try:
        with httpx.stream("GET", url, follow_redirects=True) as resp:
            resp.raise_for_status()
            with target.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
    except httpx.HTTPStatusError as e:
        raise NetworkError(f"image download failed: HTTP {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise NetworkError(f"image download failed: {e}") from e


def _download_assets(
    opts: GlobalOpts, asset_ids: list[int], folder: Path
) -> dict[int, dict[str, str]]:
    """Resolve + download each asset into `folder`.

    Returns `{assetId: {"filename", "name"}}` for the assets that downloaded;
    ids monday didn't return, or that carry no url, are skipped.
    """
    meta = _resolve_assets(opts, asset_ids)
    if not meta:
        return {}
    folder.mkdir(parents=True, exist_ok=True)
    downloaded: dict[int, dict[str, str]] = {}
    for aid in asset_ids:
        asset = meta.get(aid)
        if asset is None:
            continue
        # Prefer the pre-signed S3 `public_url`; `url` is the protected proxy.
        url = asset.get("public_url") or asset.get("url")
        if not url:
            continue
        name = asset.get("name")
        filename = local_filename(aid, name, asset.get("file_extension"))
        _download(url, folder / filename)
        downloaded[aid] = {"filename": filename, "name": name or ""}
    return downloaded


def download_doc_images(
    opts: GlobalOpts, blocks: list[dict[str, Any]], folder: Path
) -> dict[str, tuple[str, str]]:
    """Download every image block's asset into `folder`.

    Returns the `images` map `blocks_to_markdown` expects:
    `str(assetId) → (alt_text, local_filename)`, with the asset name as alt.
    """
    asset_ids = collect_image_asset_ids(blocks)
    downloaded = _download_assets(opts, asset_ids, folder)
    return {str(aid): (info["name"], info["filename"]) for aid, info in downloaded.items()}


def localize_markdown_images(
    opts: GlobalOpts, markdown: str, folder: Path
) -> tuple[str, list[str]]:
    """Download images referenced in a server-rendered markdown string and
    rewrite their URLs to the downloaded local filenames.

    Returns `(rewritten_markdown, local_filenames)`. The filename list covers
    only images that were actually downloaded + rewritten — assets monday
    didn't return keep their remote URL and are excluded.
    """
    asset_ids = extract_asset_ids_from_markdown(markdown)
    downloaded = _download_assets(opts, asset_ids, folder)
    filenames = {aid: info["filename"] for aid, info in downloaded.items()}
    return rewrite_markdown_images(markdown, filenames), list(filenames.values())
