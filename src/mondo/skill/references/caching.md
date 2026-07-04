# Caching

`mondo` keeps a local on-disk cache so repeated reads don't re-hit the monday API. Two tiers: **directory caches** (account-wide lists — `boards`, `workspaces`, `users`, `teams`, `docs`, `folders`, `tags`) and **per-scope detail caches** (`board_details`, `board_items`, `items`, `subitems`, `updates`, `docs_blocks`, plus per-board `columns`/`groups`/`webhooks`). Each entity has its own TTL; a read is served from disk until it expires. Invalidation is **local-process only** — another terminal's write is not seen until the TTL lapses or you force a refresh. Full TTL table + design notes: `docs/caching.md`.

## Escape hatches on any cached read

Every cached read command (`board get/list`, `item get/list`, `doc get`, `column list`, `group list`, `update list --item`, name searches, …) accepts:

```bash
mondo board get 123 --no-cache        # skip the cache for this call (don't read or write)
mondo board get 123 --refresh-cache   # force a live refetch and rewrite the cache
```

*Gotcha:* `--no-cache` and `--refresh-cache` together are a usage error (exit 2). Don't sprinkle `--no-cache` on name searches "to be safe" — the directory cache **is** the fast path; use `--refresh-cache` only when you have a concrete staleness reason (someone just renamed/created the thing you're looking for).

*Gotcha:* cached reads may print `cache: hit (entity=…, age=…)` to **stderr** (never stdout). Suppress with `MONDO_NO_CACHE_NOTICE=1`. Filtered `item list` variants, account-wide `update list`, and raw `mondo graphql` are always live (never cached).

## Inspect the cache — `cache status`

```bash
mondo cache status                # every cache type
mondo cache status items          # one type; scoped types list one row per file on disk
```

```json
[{"type": "boards", "path": "…/boards.json", "fetched_at": "2026-07-02T14:12:57Z",
  "age": "3h57m", "ttl_seconds": 28800, "fresh": true, "stale": false, "entries": 6222}]
```

`fresh` = servable now. `stale` = a file exists on disk but has aged past its TTL (reclaimable dead weight). A cold type (no file) is both `fresh: false` and `stale: false`. In table output, a footer hint appears when any file is stale. Filter to just the reclaimable ones with a projection:

```bash
mondo cache status -q "[?stale].path"
```

## Reclaim stale files — `cache clear`

```bash
mondo cache clear --stale         # delete ONLY files past their TTL; keep fresh ones
mondo cache clear items           # delete every per-item cache file
mondo cache clear                 # delete everything (all types)
mondo cache clear columns --board 42   # one board's column cache
mondo --dry-run cache clear --stale    # preview what would be removed; deletes nothing
```

*Gotcha:* `--stale` is endpoint- and schema-aware: it never removes a file written against a different monday endpoint (those are deliberately kept for when you switch back) or a wrong-schema file (those self-heal on the next read). It only reclaims caches genuinely expired for the current profile. Plain `cache clear` (no `--stale`) removes regardless of age.

*Gotcha:* `--board` is only valid for the board-scoped types (`columns`, `groups`, `webhooks`, `board_details`); passing it with other types is a usage error.

## Force a live refetch — `cache refresh`

```bash
mondo cache refresh boards             # refetch the boards directory
mondo cache refresh columns --board 42 # refetch one board's columns
mondo cache refresh columns            # refetch every board already in the columns cache
```

*Gotcha:* the per-item / per-doc caches (`items`, `board_items`, `subitems`, `updates`, `docs_blocks`) **can't** be refreshed here — each needs a specific id only the read site knows. Use the read command's `--refresh-cache` instead (e.g. `mondo item get 999 --refresh-cache`). Refreshable scoped types are `columns`, `groups`, `webhooks`, `board_details`.

## Profiles

All cache commands honor `--profile`, operating on that profile's own cache dir:

```bash
mondo --profile acme cache status
```

Cache types (for `status` / `refresh` / `clear`): `boards`, `workspaces`, `users`, `teams`, `docs`, `folders`, `tags`, `webhooks`, `columns`, `groups`, `board_details`, `items`, `board_items`, `subitems`, `updates`, `docs_blocks`, `all` (default).
