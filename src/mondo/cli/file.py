"""`mondo file` — upload/download monday assets (Phase 3g).

Per monday-api.md §11.5.23:
- Uploads go to a separate endpoint, `/v2/file`, as multipart.
- Do NOT set Content-Type manually — httpx picks the multipart boundary.
- Max 500 MB/upload.

`mondo file upload` writes a file to a `file`-typed column on an item
(default) or attaches it to an update. `mondo file download` fetches an
asset's URL via `assets(ids)` and streams the bytes to disk.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
import typer

from mondo.api.errors import MondoError, NetworkError
from mondo.api.queries import (
    ASSETS_GET,
    FILE_UPLOAD_ITEM,
    FILE_UPLOAD_UPDATE,
)
from mondo.cli._examples import epilog_for
from mondo.cli._exec import client_or_exit
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class UploadTarget(StrEnum):
    item = "item"
    update = "update"


# ----- upload -----


@app.command("upload", epilog=epilog_for("file upload"))
def upload_cmd(
    ctx: typer.Context,
    file_path: Path = typer.Option(
        ..., "--file", help="Local file to upload.", exists=True, readable=True
    ),
    target: UploadTarget = typer.Option(
        UploadTarget.item,
        "--target",
        help="Attach to an item's file column (default) or to an update.",
        case_sensitive=False,
    ),
    item_id: int | None = typer.Option(
        None, "--item", help="Item ID (required when --target item)."
    ),
    column_id: str | None = typer.Option(
        None, "--column", help="File-type column ID (required when --target item)."
    ),
    update_id: int | None = typer.Option(
        None, "--update", help="Update ID (required when --target update)."
    ),
    filename: str | None = typer.Option(
        None, "--filename", help="Override the filename sent to monday (default: basename)."
    ),
) -> None:
    """Upload a file to a file-column on an item or attach it to an update."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)

    if target is UploadTarget.item:
        if item_id is None or column_id is None:
            typer.secho(
                "error: --target item requires both --item and --column.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2)
        query = FILE_UPLOAD_ITEM
        variables: dict[str, Any] = {"item": item_id, "col": column_id, "file": None}
        response_key = "add_file_to_column"
    else:
        if update_id is None:
            typer.secho(
                "error: --target update requires --update.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=2)
        query = FILE_UPLOAD_UPDATE
        variables = {"update": update_id, "file": None}
        response_key = "add_file_to_update"

    if opts.dry_run:
        opts.emit(
            {
                "endpoint": "/v2/file",
                "query": query,
                "variables": {**variables, "file": f"<multipart:{file_path}>"},
                "filename": filename or file_path.name,
            }
        )
        raise typer.Exit(0)

    client = client_or_exit(opts)
    try:
        with client:
            result = client.upload_file(
                query=query,
                variables=variables,
                file_path=str(file_path),
                file_field="file",
                filename=filename,
            )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e
    data = result.get("data") or {}
    opts.emit(data.get(response_key) or {})


# ----- download -----


def _resolve_download_target(out: Path | None, asset: dict[str, Any], asset_id: int) -> Path:
    """On-disk path for an asset: `out` verbatim, `out/name` if `out` is a dir, else `name` in CWD."""
    asset_name = asset.get("name") or f"asset-{asset_id}"
    if out is None:
        return Path(asset_name)
    if out.is_dir():
        return out / asset_name
    return out


@app.command("download", epilog=epilog_for("file download"))
def download_cmd(
    ctx: typer.Context,
    asset_ids: list[int] = typer.Option(
        ..., "--asset", help="Asset ID to download. Repeatable to fetch multiple assets."
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help=(
            "Output path. If it points at an existing directory, the asset's "
            "original filename is appended. Default: asset's original name in the CWD. "
            "When downloading multiple assets, --out must be an existing directory."
        ),
    ),
) -> None:
    """Download one or more assets by ID.

    Fetches pre-signed URLs via `assets(ids)` then streams the bytes to disk.
    """
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"ids": asset_ids}
    if opts.dry_run:
        opts.emit({"query": ASSETS_GET, "variables": variables})
        raise typer.Exit(0)

    if len(asset_ids) > 1 and out is not None and not out.is_dir():
        typer.secho(
            "error: --out must be an existing directory when downloading multiple assets.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    client = client_or_exit(opts)
    results: list[dict[str, Any]] = []
    try:
        with client:
            result = client.execute(ASSETS_GET, variables=variables)
            assets = ((result.get("data") or {}).get("assets")) or []
            found_ids = {int(a["id"]) for a in assets if a.get("id") is not None}
            missing = [i for i in asset_ids if i not in found_ids]
            if missing:
                label = "asset" if len(missing) == 1 else "assets"
                typer.secho(
                    f"{label} not found: {', '.join(str(i) for i in missing)}",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=6)

            by_id = {int(a["id"]): a for a in assets}
            for aid in asset_ids:
                asset = by_id[aid]
                # Prefer the pre-signed S3 `public_url` — monday's `url` is a
                # protected_static proxy that returns 406 to non-browser clients.
                url = asset.get("public_url") or asset.get("url")
                if not url:
                    typer.secho(
                        f"asset {aid} has no url.",
                        fg=typer.colors.RED,
                        err=True,
                    )
                    raise typer.Exit(code=6)
                target = _resolve_download_target(out, asset, aid)
                try:
                    with httpx.stream("GET", url, follow_redirects=True) as resp:
                        resp.raise_for_status()
                        with target.open("wb") as fh:
                            for chunk in resp.iter_bytes():
                                fh.write(chunk)
                except httpx.HTTPStatusError as e:
                    raise NetworkError(f"download failed: HTTP {e.response.status_code}") from e
                except httpx.RequestError as e:
                    raise NetworkError(f"download failed: {e}") from e
                results.append(
                    {
                        "asset_id": asset.get("id"),
                        "name": asset.get("name"),
                        "out": str(target),
                        "bytes": target.stat().st_size,
                    }
                )
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit(results[0] if len(results) == 1 else results)
