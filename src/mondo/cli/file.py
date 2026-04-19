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

from mondo.api.client import MondayClient
from mondo.api.errors import MondoError, NetworkError
from mondo.api.queries import (
    ASSETS_GET,
    FILE_UPLOAD_ITEM,
    FILE_UPLOAD_UPDATE,
)
from mondo.cli.context import GlobalOpts

app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


class UploadTarget(StrEnum):
    item = "item"
    update = "update"


# ----- helpers -----


def _client_or_exit(opts: GlobalOpts) -> MondayClient:
    try:
        return opts.build_client()
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e


def _dry_run(opts: GlobalOpts, payload: dict[str, Any]) -> None:
    opts.emit(payload)
    raise typer.Exit(0)


# ----- upload -----


@app.command("upload")
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
        _dry_run(
            opts,
            {
                "endpoint": "/v2/file",
                "query": query,
                "variables": {**variables, "file": f"<multipart:{file_path}>"},
                "filename": filename or file_path.name,
            },
        )

    client = _client_or_exit(opts)
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


@app.command("download")
def download_cmd(
    ctx: typer.Context,
    asset_id: int = typer.Option(..., "--asset", help="Asset ID to download."),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Output path. Default: asset's original name in the CWD.",
    ),
) -> None:
    """Download an asset by ID. Fetches its pre-signed URL via `assets(ids)` then streams the bytes."""
    opts: GlobalOpts = ctx.ensure_object(GlobalOpts)
    variables = {"ids": [asset_id]}
    if opts.dry_run:
        opts.emit({"query": ASSETS_GET, "variables": variables})
        raise typer.Exit(0)

    client = _client_or_exit(opts)
    try:
        with client:
            result = client.execute(ASSETS_GET, variables=variables)
            assets = ((result.get("data") or {}).get("assets")) or []
            if not assets:
                typer.secho(
                    f"asset {asset_id} not found.",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=6)
            asset = assets[0]
            url = asset.get("url")
            if not url:
                typer.secho(
                    f"asset {asset_id} has no url.",
                    fg=typer.colors.RED,
                    err=True,
                )
                raise typer.Exit(code=6)
            target = out if out is not None else Path(asset.get("name") or f"asset-{asset_id}")
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
    except MondoError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=int(e.exit_code)) from e

    opts.emit(
        {
            "asset_id": asset.get("id"),
            "name": asset.get("name"),
            "out": str(target),
            "bytes": target.stat().st_size,
        }
    )
