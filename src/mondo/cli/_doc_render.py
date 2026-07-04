"""Rendering / export / image helpers for `mondo doc get`.

Extracted from `mondo.cli.doc` (pure move). Covers the PDF image-src
sanitizer, the server-side markdown export flow, and the per-format
render+write blocks pulled out of `get_cmd`'s body.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

import typer

from mondo.api.errors import MondoError
from mondo.api.queries import EXPORT_MARKDOWN_FROM_DOC
from mondo.cli._doc_fetch import _execute_doc_command, _fail_with_object_id_hint
from mondo.cli._exec import handle_mondo_error_or_exit
from mondo.cli.context import GlobalOpts

# Image `src` neutralization for PDF export. WeasyPrint dereferences URLs while
# converting, so before HTML reaches it we keep ONLY base64 data URIs whose
# decoded bytes are a known *raster* image, and blank everything else (remote /
# `file://` URLs from untrusted doc content, non-data srcs, and SVG).
#
# The declared MIME is NOT trusted: WeasyPrint content-sniffs and will parse SVG
# out of a `data:image/png` URI, then fetch the external resources an SVG can
# reference (verified — that's an SSRF). So we validate the actual leading
# bytes against raster magic numbers; SVG/XML and anything non-raster never
# survive regardless of the declared type. Rasters are inert pixel data and
# can't fetch. Safe on our own output: image src/alt are HTML-escaped, so no
# literal `"` appears inside an attribute value.
_IMG_SRC = re.compile(r'src="([^"]*)"')
_DATA_URI_B64 = re.compile(r"data:[\w.+/-]*;base64,(.*)", re.IGNORECASE | re.DOTALL)
_RASTER_MAGIC = (
    b"\x89PNG\r\n\x1a\n",  # png
    b"\xff\xd8\xff",  # jpeg
    b"GIF87a",
    b"GIF89a",
    b"BM",  # bmp
    b"II*\x00",  # tiff, little-endian
    b"MM\x00*",  # tiff, big-endian
)


def _is_raster_data_uri(src: str) -> bool:
    """True only for a `data:...;base64,` URI whose decoded bytes start with a
    known raster image signature (so SVG/XML and non-images are rejected even
    when they declare an `image/png` MIME)."""
    m = _DATA_URI_B64.match(src)
    if m is None:
        return False
    prefix = m.group(1)[:64]
    prefix = prefix[: len(prefix) // 4 * 4]  # whole base64 groups → clean decode
    try:
        head = base64.b64decode(prefix)
    except ValueError:
        return False
    return head.startswith(_RASTER_MAGIC) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")


def _sanitize_pdf_image_srcs(html_text: str) -> str:
    """Blank every `<img>` src that isn't a base64 raster image data URI."""
    return _IMG_SRC.sub(
        lambda m: m.group(0) if _is_raster_data_uri(m.group(1)) else 'src=""',
        html_text,
    )


def _render_html(opts: GlobalOpts, doc: dict[str, Any], *, out: Path | None, no_images: bool) -> None:
    """Render the doc's blocks to self-contained HTML (images base64-embedded)
    and either write to `--out` or echo to stdout."""
    from mondo.docs import blocks_to_html

    blocks = doc.get("blocks") or []
    images: dict[str, tuple[str, str]] = {}
    if not no_images:
        from mondo.cli._doc_images import embed_doc_images

        images = embed_doc_images(opts, blocks)
    html_text = blocks_to_html(blocks, images=images, title=doc.get("name"))
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html_text, encoding="utf-8")
        opts.emit({"out": str(out), "images": len(images)})
        return
    typer.echo(html_text)


def _render_pdf(opts: GlobalOpts, doc: dict[str, Any], *, out: Path, no_images: bool) -> None:
    """Render the doc to PDF via WeasyPrint (issue #68): the same self-contained
    HTML, image srcs sanitized, handed to the PDF engine. `--out` is required."""
    from mondo.cli._doc_images import embed_doc_images
    from mondo.cli._pdf import find_weasyprint, install_hint, render_pdf
    from mondo.docs import blocks_to_html

    # Preflight before the (network) image embed so a first-time user without
    # WeasyPrint gets the install hint without paying for asset downloads.
    if find_weasyprint() is None:
        handle_mondo_error_or_exit(MondoError(install_hint()))

    blocks = doc.get("blocks") or []
    images = {} if no_images else embed_doc_images(opts, blocks)
    html_text = blocks_to_html(blocks, images=images, title=doc.get("name"))
    html_text = _sanitize_pdf_image_srcs(html_text)
    try:
        render_pdf(html_text, out)
    except MondoError as e:
        handle_mondo_error_or_exit(e)
    opts.emit({"out": str(out), "engine": "weasyprint", "images": len(images)})


def _render_markdown(
    opts: GlobalOpts,
    doc: dict[str, Any],
    *,
    mdx: bool,
    out: Path | None,
    no_images: bool,
) -> None:
    """Render the doc's blocks to markdown (or mdx). With `--out`, embedded
    images are downloaded into the output folder and referenced locally;
    without `--out`, monday image URLs are kept."""
    from mondo.docs import blocks_to_markdown, blocks_to_mdx

    render = blocks_to_mdx if mdx else blocks_to_markdown
    blocks = doc.get("blocks") or []
    if out is not None:
        images: dict[str, tuple[str, str]] = {}
        if not no_images:
            from mondo.cli._doc_images import download_doc_images

            images = download_doc_images(opts, blocks, out.parent)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(blocks, images=images), encoding="utf-8")
        opts.emit(
            {
                "out": str(out),
                "images": [ref for _, ref in images.values()],
            }
        )
        return
    typer.echo(render(blocks))


def _emit_server_markdown(
    opts: GlobalOpts,
    *,
    doc_id: int | None,
    object_id: int | None,
    block_id: list[str] | None,
    raw: bool,
    out: Path | None,
    no_images: bool,
) -> None:
    """Render a doc to markdown via monday's server-side `export_markdown_from_doc`
    (`doc get --format markdown --engine server`). Always live; supports `--block`
    subset export and `--raw` envelope passthrough.
    """
    data, _ = _execute_doc_command(
        opts,
        EXPORT_MARKDOWN_FROM_DOC,
        {"blocks": block_id or None},
        doc_id=doc_id,
        object_id=object_id,
    )
    result = data.get("export_markdown_from_doc") or {}
    if raw:
        opts.emit(result)
        return
    if not result.get("success"):
        _fail_with_object_id_hint(
            opts, result.get("error") or "export_markdown_from_doc failed", doc_id
        )
    from mondo.docs import coalesce_markdown_emphasis

    # Monday's exporter fragments contiguous bold runs into adjacent `**…**`
    # spans; rejoin them so the markdown reads as one span (#62).
    markdown = coalesce_markdown_emphasis(result.get("markdown") or "")
    if out is not None:
        from mondo.cli._doc_images import localize_markdown_images

        images: list[str] = []
        if not no_images:
            markdown, images = localize_markdown_images(opts, markdown, out.parent)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown)
        opts.emit({"out": str(out), "images": images})
        return
    typer.echo(markdown)
