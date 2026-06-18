# Boards, workdocs, and items — reading monday URLs

monday.com renders three object kinds under URLs that look alike:

    /boards/<id>                 # real board          → mondo board get <id>
    /boards/<id>                 # workdoc (!)         → mondo doc get --object-id <id>
    /boards/<bid>/pulses/<iid>   # item (or subitem)   → mondo item get <iid>

monday models every workdoc as a board with `type == "document"`, which
is why the URL still says `/boards/` for both.

## Tell a board from a workdoc

    $ mondo board get <id> -q type -o none
    board        # real board
    document     # workdoc — switch to `mondo doc get --object-id <id>`

`mondo board get` prints a stderr warning whenever it detects
`type == "document"` so scripts watching stderr can branch immediately.

`mondo doc get --object-id` returns the inverse hint: if the id is a
regular board, the not-found message points at `mondo board get`.

## URL acceptance

Paste the browser URL directly into any of:

    mondo board get   https://<tenant>.monday.com/boards/<id>
    mondo doc get --object-id  https://<tenant>.monday.com/boards/<id>
    mondo item get    https://<tenant>.monday.com/boards/<bid>/pulses/<iid>
    mondo subitem get https://<tenant>.monday.com/boards/<bid>/pulses/<iid>

URLs are parsed locally (no network call). For items / subitems, the
board portion of the URL is discarded — the pulse id is globally unique.

## Get a URL back out of a payload

Pass `--with-url` on `board get`, `board create`, `item get`,
`subitem get`, or `item create` to include a canonical monday URL in
the emitted payload:

    $ mondo item get 12345 --with-url -q url -o none
    https://<tenant>.monday.com/boards/42/pulses/12345

    # Combined create + URL retrieval (no follow-up GET needed):
    $ mondo item create --board 42 --name "New" --with-url -q url -o none
    https://<tenant>.monday.com/boards/42/pulses/99

`mondo doc get` always includes `url` (monday's `docs()` endpoint returns
it); `--with-url` there is accepted but has no effect. `mondo doc create`
behaves the same way: its payload always includes `url`, so the flag is
a no-op there too.

On `board list` and `doc list`, `--with-url` is opt-in: the default output
has no `url` / `relative_url` so the two commands emit the same core shape.
Pass `--with-url` on either to get URLs back.

## Once you've found a workdoc

Render it to a markdown file (embedded images are downloaded alongside it,
referenced by local filename — the raw monday image URLs only resolve in a
logged-in browser):

    mondo doc get --object-id <id> --format markdown --out ./doc.md
    mondo doc export-markdown --object-id <id> --out ./doc.md   # server-side render

Pass `--no-images` to skip the download and keep the original URLs. To write
content back — replace a doc in place, or create one inside a folder — see
`mondo help` and the bundled `references/docs.md` (`doc set` / `doc replace`,
`doc create --folder`).

## Agent workflow

1. Paste any monday URL into the command that matches its shape.
2. If `board get` surfaces `type == "document"`, re-issue as
   `doc get --object-id <id>` to get the doc's block tree.
3. Pass `--with-url` whenever you need to hand a human (or another tool)
   a link back to the monday UI — including on `item create`, so the
   create response carries the URL directly (no second round-trip).

## `board list` / `doc list`

`mondo board list` hides workdocs by default — pass `--type doc` or
`--type all`. `mondo doc list` always queries the `docs()` endpoint and
only ever returns workdocs.
