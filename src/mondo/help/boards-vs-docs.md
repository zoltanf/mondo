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

Pass `--with-url` on `board get`, `item get`, or `subitem get` to include
a canonical monday URL in the emitted payload:

    $ mondo item get 12345 --with-url -q url -o none
    https://<tenant>.monday.com/boards/42/pulses/12345

`mondo doc get` always includes `url` (monday's `docs()` endpoint returns
it); `--with-url` there is accepted but has no effect.

On `board list` and `doc list`, `--with-url` is opt-in: the default output
has no `url` / `relative_url` so the two commands emit the same core shape.
Pass `--with-url` on either to get URLs back.

## Agent workflow

1. Paste any monday URL into the command that matches its shape.
2. If `board get` surfaces `type == "document"`, re-issue as
   `doc get --object-id <id>` to get the doc's block tree.
3. Pass `--with-url` whenever you need to hand a human (or another tool)
   a link back to the monday UI.

## `board list` / `doc list`

`mondo board list` hides workdocs by default — pass `--type doc` or
`--type all`. `mondo doc list` always queries the `docs()` endpoint and
only ever returns workdocs.
