# Introspection and error handling for agents

Companion to `mondo help agent-workflow` (call shape, exit codes,
flag aliases). This topic covers how to discover what fields you can
project, why `-q` sometimes returns `null`, and how to parse errors
into a retry decision.

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
| `item get`        | `--with-url`                                        |
| `item duplicate`  | `--with-updates`                                    |
| `subitem get`     | `--with-url`                                        |
| `doc list`        | `--with-url`                                        |
| `doc get`         | `--with-url`                                        |

Some of these (e.g. `--with-item-counts`, `--with-tags`) bypass the
local cache because the extra fields aren't cached — read each
command's `--help` for the trade-offs.

## Cache provenance

Read commands that hit the local directory cache emit one stderr
line so you can tell cached results from live ones:

    cache: hit (entity=boards, age=2m, count=143)

Suppress with `MONDO_NO_CACHE_NOTICE=1`. The line is also auto-
suppressed in `-o table` mode (TTY humans don't usually want it).

For verbose detail (cache path, ttl, exact fetched-at), pass
`--explain-cache` on the read command:

    cache: hit (entity=boards, count=143, age=2m, ttl=86400s, fetched_at=2026-04-30T11:22:33+00:00, path=/Users/.../mondo/cache/boards.json)

`--explain-cache` is supported on `board list`, `folder list/tree`,
`workspace list`, `user list`, `team list`, `doc list`. To force a
fresh fetch use `--no-cache` or `--refresh-cache`.

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
