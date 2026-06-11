# Introspection and error handling for agents

Companion to `mondo help agent-workflow` (call shape, exit codes,
flag aliases). This topic covers how to discover what fields you can
project, why `-q` sometimes returns `null`, and how to parse errors
into a retry decision.

## Narrow server-side — the cost model

On boards beyond a few hundred items a full `item list` costs ~10s per
500 items, and the full `column_values` selection is ~3x the bare item
fields. Narrow on the server, not in `-q`:

    # Server-side: group + filter + cap
    mondo item list --board 123 --group g1 --filter status=Done --max-items 50

    # Canonical cheap id-lookup (auto-drops column_values -> ~3x faster)
    mondo item list --board 123 --group g1 --fields id,name

    # Only the column values you need, server-side
    mondo item list --board 123 --columns status,person

    # Lookup by column value
    mondo item find --board 123 --column status --value Done

Reach for `-q` to *project* fields, not to *filter* rows — a client-side
`[?group.id=='...']` still pays for every item on the board. Repeat
listings of the same board within 60s are served from the board-items
cache (bare `--board` / `--group` variants only).

Name-search over the directories (`board / doc / folder list
--name-contains`) is served from an 8h cache; the first cold search of
the day pays the full directory fetch (parallelized, but still the
expensive step). Don't add `--no-cache` to name searches out of caution
— the cache IS the fast path.

## Never suppress stderr

Don't append `2>/dev/null` to mondo calls. Errors, recovery hints, and
the structured error envelope live on stderr — suppressed, a failure is
just empty stdout + a nonzero exit code, followed by confusing
downstream breakage (`json.load` on empty input). Benign notices (cache
hits, skill-freshness warnings) are already withheld in non-TTY runs, so
stderr is errors-only in pipelines. Use `2>&1` or leave stderr attached,
and branch on the exit code. As a backstop, fatal errors in machine mode
also mirror the JSON envelope to stdout when nothing else has been
written there.

## Discover the selection set with `mondo schema`

Every `mondo X get` / `mondo X list` runs a fixed GraphQL selection
set. Project on a field that's *not* in the set and `-q` returns
`null` — JMESPath can't tell "missing" from "empty". `mondo schema`
prints the truth, so you can plan projections without trial and
error.

    mondo schema                # every resource
    mondo schema board          # one resource
    mondo schema board -q "get" # the field list for `mondo board get`

Output shape:

    {
      "board": {
        "get":  ["id", "name", "owners", ...],
        "list": ["id", "name", "state", "workspace_id", ...]
      },
      "item": { "get": [...], "list": [...] },
      ...
    }

Resources covered: `board`, `column`, `doc`, `folder`, `group`,
`item`, `subitem`, `team`, `update`, `user`, `workspace`. Each
exposes `get`, `list`, or both (depending on what reads exist).

## Projection warnings on stderr

If your `-q` projection references a field that wasn't in the
selection set, `mondo` writes one yellow line per missing field to
stderr and **still emits the projection**:

    warning: field 'board_folder_id' is not in the GraphQL selection set

Two ways to make it go away:

- **Add the field to the selection set** with a `--with-*` flag
  (next section), if one exists for that field.
- **Suppress the warning** with `MONDO_NO_PROJECTION_WARNINGS=1` when
  you're knowingly projecting onto something that may be empty.

## Opt-in selection-set extensions

A few commands accept `--with-*` flags that extend the default
selection set. Reach for one of these *before* dropping to `mondo
graphql`:

| Command           | Available `--with-*` flags                          |
|-------------------|-----------------------------------------------------|
| `board list`      | `--with-item-counts`, `--with-url`, `--with-tags`   |
| `board get`       | `--with-url`, `--with-views`                        |
| `board create`    | `--with-url` (returns the new board's URL without a follow-up GET) |
| `item get`        | `--with-url`                                        |
| `item create`     | `--with-url` (returns the new item's URL without a follow-up GET) |
| `item duplicate`  | `--with-updates`                                    |
| `subitem get`     | `--with-url`                                        |
| `doc list`        | `--with-url`                                        |
| `doc get`         | `--with-url`                                        |
| `doc create`      | `--with-url` (no-op: the create payload always carries `url`; accepted for symmetry) |

Some of these (e.g. `--with-item-counts`, `--with-tags`) bypass the
local cache because the extra fields aren't cached — read each
command's `--help` for the trade-offs.

## Where the data-shaping flags live in `--help`

`--output / -o`, `--query / -q`, and `--fields` are surfaced in a
dedicated **"Output / Query"** Rich help panel on every subcommand — not
buried in "Global Options". Scan there first when you need to project,
filter client-side, or change format. For the most common projection
shape ("give me id, name, status"), `--fields id,name,status` is
shorter than the equivalent `-q '[].{id:id,name:name,status:status}'`.

## Cache provenance

Read commands that hit the local directory cache can emit one stderr
line so you can tell cached results from live ones:

    cache: hit (entity=boards, age=2m, count=143)

Since #25 the line is suppressed by default when stderr is not a TTY
(the typical agent context) — re-enable it with `--verbose` or
`MONDO_VERBOSE=1`. On a TTY, suppress it with `MONDO_NO_CACHE_NOTICE=1`;
it is also auto-suppressed in `-o table` mode (TTY humans don't usually
want it).

For verbose detail (cache path, ttl, exact fetched-at), pass
`--explain-cache` on the read command:

    cache: hit (entity=boards, count=143, age=2m, ttl=86400s, fetched_at=2026-04-30T11:22:33+00:00, path=/Users/.../mondo/cache/boards.json)

`--explain-cache` is supported on every cached read: directory
listings (`board / workspace / user / team / doc / folder / tag list`,
`folder tree`, `webhook list`), the single-entity gets that short-
circuit through the directory cache (`workspace / folder / team get`,
`tag get`), and the per-board / per-item / per-doc caches (`board get`,
`item get`, `subitem list/get`, `update list --item`, `doc get`). To
force a fresh fetch use `--no-cache` or `--refresh-cache` on the same
command. See `docs/caching.md` for the per-entity TTL table.

## Structured error envelope (`-o json|jsonc|yaml`)

Every CLI error in machine-output mode emits a JSON line on
**stderr** alongside the human-readable `error: ...` line. Fields:

- `error` — human-readable message (always).
- `code` — string identifier: `AuthError`, `RateLimitError`,
  `ValidationError`, `NoSuchOption`, `MissingParameter`, ... (always).
- `exit_code` — integer matching the process exit code; branch on
  this (always).
- `request_id` — monday's request id; present on server-side failures.
- `retry_in_seconds` — present on rate/complexity errors.
- `suggestion` — present on flag typos (e.g. `--group-id` →
  suggests `--group` / `--id`).

Null fields are dropped, so `jq` over the line is straightforward.
Two examples:

    # Auth failure
    $ mondo --api-token bogus -o json board list 2>&1 >/dev/null | tail -1
    {"error":"...","code":"AuthError","exit_code":3,"request_id":"..."}

    # Flag typo
    $ mondo -o json board get --not-real-flag 1 2>&1 >/dev/null | head -1
    {"error":"No such option: --not-real-flag","code":"NoSuchOption","exit_code":2,"suggestion":"did you mean ...?"}

The envelope is auto-detected when stdout isn't a TTY even without
`-o json`, so an agent gets it for free; pass an explicit human
format (`-o table|tsv|csv`) to opt out.

The full retry decision tree is in `mondo help exit-codes`.

## The `mondo graphql` escape hatch

When `mondo schema` shows the field you want isn't selected and no
`--with-*` flag exists, drop to raw GraphQL:

    mondo graphql 'query { boards(ids:[123]) { board_folder_id } }'

`mondo graphql` skips codecs, complexity injection, and pagination —
you're talking to monday directly with the same auth and exit codes.
`--dry-run` is also unsupported on this command: it's refused with
exit 2 rather than silently sending, since mondo can't preview a
query it doesn't parse. Eyeball your GraphQL before running.
See `mondo help graphql` for the input forms (inline / `@file` /
stdin) and variables.

## See also

- `mondo help agent-workflow` — call shape, exit codes, retries.
- `mondo help duplicate-and-customize` — end-to-end workflow
  walkthrough.
- `mondo help batch-operations` — bulk primitives + title-based
  selectors.
- `mondo help exit-codes` — full retry decision table.
- `mondo help graphql` — the raw-passthrough escape hatch.
