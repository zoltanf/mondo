# Local directory cache

`mondo` keeps a small on-disk cache for slowly- and moderately-changing
entities — boards, workspaces, users, teams, workspace docs, per-board column
and group definitions, plus newer per-board / per-item / per-doc caches — so
that read commands don't re-walk the monday API on every invocation. This is
a **performance optimization**, never a data store: any cache-path failure
degrades silently to the live API.

Every read command that consults a cache exposes `--no-cache` (live bypass)
and `--refresh-cache` (force-refetch + write-through), grouped under a
"Cache" panel in `--help`. The pair are mutually exclusive.

## What's cached

| Entity | Scope | What's stored |
|---|---|---|
| boards | global | directory entries: id, name, description, state, kind, folder_id, workspace_id, created_at, updated_at, type, `workspace { id name }` |
| workspaces | global | id, name, kind, description, state, created_at |
| users | global | id, name, email, enabled, is_admin, is_guest, is_pending, is_view_only, created_at, last_activity, title |
| teams | global | id, name, picture_url, is_guest (plus nested `users` and `owners`) |
| docs | global | id, object_id, name, kind, folder_id, workspace_id, created_at, updated_at, url, relative_url, created_by |
| folders | global | normalized folder rows: id, name, color, workspace_id/name, parent_id/name, owner_id, created_at |
| columns | per-board | id, title, type, description, archived, settings_str |
| groups | per-board | id, title, color, position, archived |
| tags | global | account-level public tags: id, name, color |
| webhooks | per-board | id, board_id, event, config |
| board_details | per-board | full `BOARD_GET` payload **minus `items_count`**; the count is fetched live and merged on read |
| items | per-item | full `ITEM_GET` payload (also serves `subitem get`) |
| subitems | per-parent-item | subitems list |
| updates | per-item | item's updates list with replies/likes/pinning |
| docs_blocks | per-doc | full doc payload with the merged block tree |

`<profile>` subdirectory keeps caches from different monday accounts from
colliding. Single-file types live at `<cache_dir>/<profile>/<entity>.json`;
scoped types at `<cache_dir>/<profile>/<entity>/<scope>.json`.

### Population is concurrent (#20)

Page-based collections (boards, workspaces, users, docs, folders) have
independently addressable pages, so directory population fetches page 1
serially and then pages 2..N in waves of 4 workers (the docs directory
additionally fans its per-workspace queries through the same pool). The
result is byte-identical to the serial walk — the first short page ends
the run and later pages in the same wave are discarded. `--no-cache`
reads use the same fetch path and benefit equally.

Measured on a 5,966-board account (60 pages): serial 65s → concurrent
21s; warm cache hit 0.4s. Reproduce with `scripts/bench_directory_fetch.sh`.
Tune or disable with `MONDO_DIR_FETCH_CONCURRENCY` (default 4; `1` =
serial).

## What's NOT cached (deliberate)

- `mondo item list` at board scope, and `mondo item find` — the invalidation
  surface is too wide; one write anywhere on the board would have to drop the
  whole list. Both stay live.
- Account-wide `mondo update list` (no `--item`) — same reason. `update list
  --item <id>` IS cached.
- `mondo update get` (single update by id) — covered by the parent item's
  `updates/<item_id>.json` cache when callers list-then-get; standalone reads
  by update id stay live.
- `items_count` on boards — fetched live as a one-field query and merged onto
  cached `board_details` payloads on read. `--with-item-counts` on `board list`
  still bypasses the boards-directory cache entirely.
- Raw `mondo graphql` responses — never cached.
- The combined item+columns round-trip used by `column get/set/clear`
  (`COLUMN_CONTEXT`) — stays live because splitting it would add a round-trip.

## Stale-data risk and the `--refresh-cache` escape hatch

Short-TTL caches (items / subitems 60 s, updates / docs_blocks 5 m) trade
freshness for speed. Two callers using `mondo` from different terminals see
each other's writes only after the TTL expires, or via an explicit
`--refresh-cache`. The same is true for board / column / group / tag changes
made through the monday web UI or another API client while a `mondo` cache is
warm. When in doubt, run the read command with `--refresh-cache`.

## Storage

Files live at `$XDG_CACHE_HOME/mondo/<profile>/` (falling back to
`~/.cache/mondo/<profile>/`). Single-file types use `<entity>.json`; scoped
types use `<entity>/<scope_id>.json` — `<scope_id>` is the board id for
columns/groups/webhooks/board_details, the item id for items/subitems/
updates, and the doc id for docs_blocks.

Directory mode is `0700`; file mode is `0600`. Writes go through a temp file +
`os.replace()` so a concurrent reader never sees a torn file.

Each file holds an envelope like:

```json
{
  "schema_version": 1,
  "fetched_at": "2026-04-20T10:15:00Z",
  "ttl_seconds": 28800,
  "api_endpoint": "https://api.monday.com/v2",
  "mondo_version": "0.3.1",
  "count": 342,
  "entries": [ { "id": 123, "name": "..." }, ... ]
}
```

A cached envelope is used only when:
- `schema_version` matches the current build;
- `now - fetched_at < ttl_seconds`;
- `api_endpoint` matches the current profile's configured endpoint.

Any other state is treated as a cold cache — the file is re-fetched (and
dropped if corrupt).

## TTLs and configuration

| Entity | Default TTL |
|---|---|
| boards | 28800 s (8h) |
| workspaces | 86400 s (24h) |
| users | 86400 s (24h) |
| teams | 86400 s (24h) |
| docs | 28800 s (8h) |
| folders | 28800 s (8h) |
| columns | 3600 s (1h) |
| groups | 3600 s (1h) |
| tags | 86400 s (24h) |
| webhooks | 600 s (10m) |
| board_details | 900 s (15m) |
| items | 60 s |
| subitems | 60 s |
| updates | 300 s (5m) |
| docs_blocks | 300 s (5m) |

Override via `~/.config/mondo/config.yaml`:

```yaml
cache:
  enabled: true                 # master switch
  dir: null                     # null = use XDG default
  ttl:
    boards: 28800
    workspaces: 86400
    users: 86400
    teams: 86400
    docs: 28800
    folders: 28800
    columns: 3600
    groups: 3600
    tags: 86400
    webhooks: 600
    board_details: 900
    items: 60
    subitems: 60
    updates: 300
    docs_blocks: 300
  fuzzy:
    threshold: 70               # default --fuzzy-threshold (0-100)

# Per-profile override — merges onto the global block above.
profiles:
  acme:
    api_token_keyring: acme:token
    cache:
      ttl:
        boards: 3600            # this profile wants fresher boards
```

Or via environment variables (highest non-CLI precedence):

- `MONDO_CACHE_ENABLED` — `true|false|0|1`
- `MONDO_CACHE_DIR` — absolute directory; the per-profile subdir is appended
- `MONDO_CACHE_TTL_*` — one per entity above
  (`MONDO_CACHE_TTL_BOARDS`, `_WORKSPACES`, `_USERS`, `_TEAMS`, `_DOCS`,
  `_FOLDERS`, `_COLUMNS`, `_GROUPS`, `_TAGS`, `_WEBHOOKS`, `_BOARD_DETAILS`,
  `_ITEMS`, `_SUBITEMS`, `_UPDATES`, `_DOCS_BLOCKS`) — integer seconds
- `MONDO_CACHE_FUZZY_THRESHOLD` — integer 0-100
- `MONDO_NO_CACHE_NOTICE=1` — silence the `cache: hit (entity=…, age=…)`
  stderr provenance line on hits

Precedence (lowest → highest): built-in defaults → global `cache:` → profile
`cache:` → env vars → CLI flags (`--no-cache`, `--refresh-cache`,
`--fuzzy-threshold`).

## Filter routing on `list` commands

When the cache is live, filters are applied client-side against the cached
directory. Nothing new on the wire.

| Flag | Behavior |
|---|---|
| `--state`, `--kind`, `--workspace`, `--order-by` | Client-side against the cached directory. |
| `--name-contains`, `--name-matches` | Client-side substring/regex. Already client-side pre-change. |
| `--name-fuzzy` | Client-side fuzzy (rapidfuzz WRatio); see below. |
| `--max-items` | Client-side slice after filters + sort. |
| `--limit` | Ignored when served from cache (no pages). Used for live fetches. |
| `--with-item-counts` | **Bypasses the cache** — live fetch, cache untouched. |
| `--no-cache` | Bypass cache for this run; do not read or write it. |
| `--refresh-cache` | Force live refetch; rewrite the cache. |

`--no-cache` and `--refresh-cache` together are a usage error.

## Fuzzy name search

Each `list` command has three new flags:

- `--name-fuzzy TEXT` — tolerates typos and word-order changes.
- `--fuzzy-threshold INT` (default 70) — minimum rapidfuzz score (0-100).
- `--fuzzy-score` — include a `_fuzzy_score` field on each result and sort by
  score desc.

`--name-fuzzy` is mutually exclusive with `--name-contains` and
`--name-matches` — pick one.

Fuzzy matching is intentionally not the default: silent fuzzy-picks are a
footgun for agent pipelines. For single-best-match selection, combine
`--name-fuzzy "..." --max-items 1 --fuzzy-score` and verify the returned
score before acting on the id.

## Invalidation

1. **TTL expiry** — envelopes older than their TTL are treated as cold.
2. **Same-process mutations** — every mutation drops the caches it
   invalidates. Best-effort: a failed invalidation never fails the mutation.

   | Trigger | Drops |
   |---|---|
   | `board create/update/archive/delete/duplicate/move/set-permission` | `boards`, `board_details/<id>` |
   | `column create/rename/change-metadata/delete` | `columns/<board_id>`, `board_details/<board_id>` |
   | `column set/set-many/clear` | `items/<item_id>` (+ `columns/<board_id>` when `--create-labels-if-missing` may have minted a label) |
   | `group create/update/reorder/delete` | `groups/<board_id>`, `board_details/<board_id>` |
   | `tag create-or-get` | `tags`, `board_details/<board_id>` |
   | `webhook create` | `webhooks/<board_id>` |
   | `webhook delete` | every `webhooks/<board_id>.json` (wildcard — webhook id alone doesn't carry a board) |
   | `item rename/move/move-to-board/archive/delete` | `items/<item_id>` |
   | `subitem create` | `subitems/<parent_id>` |
   | `subitem rename/move/archive/delete` | `items/<subitem_id>` |
   | `update create` / `update clear` / `update pin/unpin --item` | `updates/<item_id>` |
   | `update reply/edit/delete/like/unlike/pin/unpin (no --item)` | every `updates/<item_id>.json` (wildcard) |
   | `doc add-block / add-content / add-markdown / column doc set/append` | `docs_blocks/<doc_id>` |
   | `doc rename/delete` | `docs_blocks/<doc_id>`, `docs` |
   | `doc import-html` | `docs` (new id; no docs_blocks to drop) |
   | `doc update-block / delete-block` | every `docs_blocks/<doc_id>.json` (wildcard — block id alone doesn't carry a doc) |
   | `column doc clear` | `items/<item_id>` |
   | workspace / folder / team / user mutations | the corresponding directory cache |

3. **Endpoint change** — switching profiles to a different monday endpoint
   treats the cache as cold.
4. **Schema version mismatch** — after a `mondo` upgrade that bumps
   `schema_version`, envelopes from the old version are dropped.

Writes from *other* processes, users, or API clients are **not** detected.
They're picked up at TTL expiry or via an explicit `mondo cache refresh` /
`--refresh-cache`. This is by design — local-process-only invalidation keeps
the contract simple at the cost of cross-process freshness.

Boards' `board_kind` / `board_folder_id` and docs' `doc_kind` / `doc_folder_id`
are renamed to `kind` / `folder_id` at the cache boundary, so both directories
emit the same core shape. `board list` and `doc list` also auto-populate the
workspaces cache on first use to enrich each row with `workspace_name`
(`"Main workspace"` when `workspace_id` is null).

## Management commands

```
mondo cache status  [<type>]
mondo cache refresh [<type>] [--board ID ...]
mondo cache clear   [<type>] [--board ID ...]
```

Where `<type>` ∈ `boards | workspaces | users | teams | docs | folders |
columns | groups | tags | webhooks | board_details | items | subitems |
updates | docs_blocks | all`. Default: `all`.

- **`cache status`** — one row per single-file type plus, for scoped types,
  one row per file already on disk. Columns: `type`, `path`, `fetched_at`,
  `age`, `ttl_seconds`, `fresh`, `entries`, and `board` (when the row is
  per-board scoped).
- **`cache refresh`** — force-refetches the selected type(s). `--board ID`
  is honored for `columns`, `groups`, `webhooks`, and `board_details`. The
  per-item / per-doc caches (`items`, `subitems`, `updates`, `docs_blocks`)
  can't be refreshed here because each needs a specific id — use the read
  command's `--refresh-cache` flag instead (e.g. `mondo item get <id>
  --refresh-cache`). Honors `--dry-run`.
- **`cache clear`** — deletes the selected cache file(s). With `--board ID`
  for board-scoped types, only those board files are removed; without it,
  every per-scope file for the selected type is removed. Idempotent. Honors
  `--dry-run`.

`--board` is only accepted when the selector includes a board-scoped type
(`columns`, `groups`, `webhooks`, `board_details`).

All three respect `--profile`, so `mondo --profile acme cache refresh`
operates on the `acme` profile's cache dir.

## Failure modes

| Situation | Observable behavior |
|---|---|
| Cache file missing | Cold → live fetch, cache written. |
| File corrupt / unparseable / wrong schema | File deleted, cold path taken, DEBUG log. |
| File present but expired | Live fetch, envelope overwritten. |
| `api_endpoint` mismatch | Treated as cold; file kept (avoids re-warming when you switch back). |
| Cache dir not writable | Fetched data served from memory; cache file not updated; WARNING logged once. |
| Two processes refresh simultaneously | Both fetch, last `os.replace` wins; both callers return correct data. |
| `rapidfuzz` import fails | Clean usage error on `--name-fuzzy` only; other flags unaffected. |
| Network failure on refresh | Usual `MondoError` propagates. Stale cache is **not** served as a fallback. |

DEBUG-level events: hits, misses, expiry, corrupt-file deletion, successful
writes. WARNING-level: write failures. No INFO-level spam on the happy path.

## Non-goals

- Cross-process locking and webhook-driven invalidation. Writes by other
  processes / users / API clients are picked up at TTL expiry or via
  `--refresh-cache` — not in real time.
- Background / pre-emptive refresh.
- Caching `mondo item list` at board scope, `mondo item find`, or
  account-wide `mondo update list` — invalidation surface too wide.
- Negative-lookup refresh (refetching because a name didn't match).
