"""Parse Monday.com URLs (or bare integer IDs) into resource IDs.

Monday renders real boards AND workdocs under `/boards/<id>`; items and
subitems under `/boards/<bid>/pulses/<iid>`. These parsers are offline —
they only extract a numeric id. Board-vs-doc resolution still happens via
an API call against `Board.type`.

This module also hosts the `--with-url` round-trip helpers: a process-
lifetime cache for the account slug (one `me { account { slug } }` query
per invocation) plus small synthesis functions for boards and items.
Monday's `Item.url` is the authoritative source for item URLs; the
`item_url()` helper is kept for symmetry and local fallback.
"""

from __future__ import annotations

import re
from typing import Any, Literal

import click
import typer

from mondo.api.client import MondayClient

IdKind = Literal["board", "item"]


_BOARD_URL_RE = re.compile(
    r"""^(?:https?://)?           # optional scheme
        (?:[\w-]+\.)?monday\.com  # tenant.monday.com
        /(?:boards|docs)          # boards OR docs path segment
        /(\d+)                    # capture board/doc id
        (?:[/?\#].*)?$            # trailing /pulses/…, /views/…, ?q, #frag
    """,
    re.VERBOSE,
)


_ITEM_URL_RE = re.compile(
    r"""^(?:https?://)?
        (?:[\w-]+\.)?monday\.com
        /boards/\d+/pulses/(\d+)  # capture pulse (item) id, discard board
        (?:[/?\#].*)?$
    """,
    re.VERBOSE,
)


def parse_monday_id(s: str, *, kind: IdKind = "board") -> int:
    """Return the numeric id in `s`. `s` may be a bare int string or a URL.

    - `kind="board"`: pulls the id after `/boards/<id>` (or `/docs/<id>`).
      A pulses-URL is accepted (the regex captures the board id before
      `/pulses/…`).
    - `kind="item"`: requires a `/pulses/<id>` segment; a bare board URL
      raises `BadParameter` pointing the user at `mondo board get`.
    """
    s = s.strip()
    if s.isdigit():
        return int(s)
    if kind == "item":
        m = _ITEM_URL_RE.match(s)
        if m:
            return int(m.group(1))
        if _BOARD_URL_RE.match(s):
            raise typer.BadParameter(
                f"URL points to a board, not an item. Try: mondo board get {s}"
            )
        raise typer.BadParameter(
            f"expected an item id or a monday.com /pulses/<id> URL, got {s!r}"
        )
    m = _BOARD_URL_RE.match(s)
    if m:
        return int(m.group(1))
    raise typer.BadParameter(
        f"expected a numeric id or a monday.com URL, got {s!r}"
    )


class MondayIdParam(click.ParamType):
    """Click ParamType accepting int-strings AND monday URLs.

    `name = "integer"` matches Click's built-in `IntParamType.name` so
    `mondo help --dump-spec` keeps reporting `--id` as an integer —
    external agent tooling pinned to that type stays compatible.
    """

    name = "integer"

    def __init__(self, *, kind: IdKind = "board") -> None:
        self.kind = kind

    def convert(
        self,
        value: Any,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> int:
        if isinstance(value, int):
            return value
        try:
            return parse_monday_id(str(value), kind=self.kind)
        except typer.BadParameter as e:
            self.fail(str(e), param, ctx)


def warn_cross_type(
    board: dict[str, Any],
    *,
    expected: Literal["board", "doc"],
    id_: int,
) -> None:
    """Emit a stderr hint when `Board.type` doesn't match the command.

    Advisory only — never mutates data, never raises. Stays silent when
    the observed type matches the expected kind.
    """
    observed = board.get("type") or "board"
    if expected == "board" and observed == "document":
        typer.secho(
            f"warning: id {id_} is a workdoc, not a board. "
            f"Consider: mondo doc get --object-id {id_}",
            fg=typer.colors.YELLOW,
            err=True,
        )
    elif expected == "doc" and observed != "document":
        typer.secho(
            f"warning: id {id_} is a regular board, not a workdoc. "
            f"Consider: mondo board get {id_}",
            fg=typer.colors.YELLOW,
            err=True,
        )


_TENANT_SLUG_CACHE: str | None = None


def get_tenant_slug(client: MondayClient) -> str:
    """Fetch and memoize the account slug for this process.

    `--with-url` on `board get` synthesizes the URL client-side; Monday's
    Board schema has no `.url` field. The one extra `me { account { slug } }`
    query per invocation is paid only when `--with-url` is actually passed.
    """
    global _TENANT_SLUG_CACHE
    if _TENANT_SLUG_CACHE is None:
        envelope = client.execute("query { me { account { slug } } }")
        data = envelope.get("data") or {}
        slug = (((data.get("me") or {}).get("account") or {}).get("slug")) or ""
        if not slug:
            raise typer.BadParameter("could not resolve account slug for URL synthesis")
        _TENANT_SLUG_CACHE = slug
    return _TENANT_SLUG_CACHE


def _reset_tenant_slug_cache_for_tests() -> None:
    """Test-only hook — resets the process-lifetime slug memo."""
    global _TENANT_SLUG_CACHE
    _TENANT_SLUG_CACHE = None


def board_url(slug: str, board_id: int) -> str:
    return f"https://{slug}.monday.com/boards/{board_id}"


def item_url(slug: str, board_id: int, item_id: int) -> str:
    return f"https://{slug}.monday.com/boards/{board_id}/pulses/{item_id}"
