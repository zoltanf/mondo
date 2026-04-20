# Local directory cache

`mondo` keeps a small on-disk cache of slowly-changing entity directories —
boards, workspaces, users, teams, workspace docs, and per-board column
definitions — so that `list` commands and column-aware mutation paths don't
re-walk the monday API on every invocation. This is a **performance
optimization**, never a data store: any cache-path failure degrades silently to
the live API.

## What's cached

| Entity | What's stored |
|---|---|
| boards | id, name, description, state, board_kind, board_folder_id, workspace_id, updated_at |
| workspaces | id, name, kind, description, state, created_at |
| users | id, name, email, enabled, is_admin, is_guest, is_pending, is_view_only, created_at, title |
| teams | id, name, picture_url, is_guest (plus nested `users` and `owners`) |
| docs | id, object_id, name, doc_kind, workspace_id, created_at, url, relative_url, created_by |
| columns (per-board) | id, title, type, description, archived, settings_str — which includes status/dropdown label sets |

## What's NOT cached

- `items_count` on boards — too volatile. `--with-item-counts` always bypasses
  the cache with a live fetch.
- Item values / activity (`mondo item get/list`, `mondo activity`) — volatile
  and out of scope.
- Raw query responses (`mondo graphql`) — never cached.
- The combined item+columns round-trip used by `column get/set/clear`
  (`COLUMN_CONTEXT`) — stays live because splitting it would add a round-trip.

## Storage

Files live at `$XDG_CACHE_HOME/mondo/<profile>/` (falling back to
`~/.cache/mondo/<profile>/`). One file per entity type: `boards.json`,
`workspaces.json`, `users.json`, `teams.json`, `docs.json`. Per-board column
caches live one-file-per-board under `columns/<board_id>.json`. The profile
subdirectory keeps caches from different monday accounts from colliding.

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
| columns | 1200 s (20m) |

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
    columns: 1200
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
- `MONDO_CACHE_TTL_BOARDS`, `MONDO_CACHE_TTL_WORKSPACES`,
  `MONDO_CACHE_TTL_USERS`, `MONDO_CACHE_TTL_TEAMS`, `MONDO_CACHE_TTL_DOCS`,
  `MONDO_CACHE_TTL_COLUMNS` — integer seconds
- `MONDO_CACHE_FUZZY_THRESHOLD` — integer 0-100

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
2. **Same-process mutations** — after a successful `board create/update/
   archive/delete/duplicate` (or the analogous workspace/user/team mutation),
   the corresponding cache file is dropped. For columns the trigger is any
   successful `column create/rename/change-metadata/delete` plus any
   `item create` / `column set` / `column set-many` / `subitem create` /
   `mondo import` run with `--create-labels-if-missing` (which may mint a new
   status/dropdown label inside `settings_str`). Invalidation runs
   best-effort; a failed invalidation never fails the mutation.
3. **Endpoint change** — switching profiles to a different monday endpoint
   treats the cache as cold.
4. **Schema version mismatch** — after a `mondo` upgrade that bumps
   `schema_version`, envelopes from the old version are dropped.

Writes from *other* processes, users, or API clients are **not** detected.
They're picked up at TTL expiry or via an explicit `mondo cache refresh`.

## Management commands

```
mondo cache status  [<type>]
mondo cache refresh [<type>] [--board ID ...]
mondo cache clear   [<type>] [--board ID ...]
```

Where `<type>` ∈ `boards | workspaces | users | teams | docs | columns | all`.
Default: `all`.

- **`cache status`** — one row per type (and, for `columns`, one row per
  per-board file already on disk) with path, fetched_at, age, ttl, fresh
  flag, entry count. Honors `--output json` etc.
- **`cache refresh`** — force-refetches the selected type(s). For `columns`,
  `--board ID` selects which boards to refresh; without it, every board
  already present in the columns cache is re-fetched (monitored set — does
  not discover additional boards on the account). Honors `--dry-run` (emits
  the plan without executing).
- **`cache clear`** — deletes the selected cache file(s). For `columns`,
  `--board ID` clears those specific files; without it, every per-board
  columns cache is removed. Idempotent. Honors `--dry-run`.

`--board` is only accepted when the selector includes `columns`.

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

- Item values / activity caching.
- Cross-process locking.
- Background / pre-emptive refresh.
- Negative-lookup refresh (refetching because a name didn't match).
- `mondo <entity> find` name-resolution helpers.

A future phase will add name→ID resolution on top of this cache, including
the miss-triggered refresh that was deferred from the original spec.
