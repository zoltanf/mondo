# Caching

`mondo` caches monday reads on local disk so repeated calls don't re-hit the
API. It's on by default, per-profile, and safe: an expired entry is never
served, and a corrupt file self-heals (it's dropped and refetched).

## What gets cached

Two tiers:

- **Directory caches** — account-wide lists, one file each: `boards`,
  `workspaces`, `users`, `teams`, `docs`, `folders`, `tags`. Longer TTLs
  (hours). These back name lookups like `board list --name-contains`.
- **Per-scope detail caches** — one file per id: per-board `columns`,
  `groups`, `webhooks`, `board_details`; per-board item lists (`board_items`);
  per-item `items`, `subitems`, `updates`; per-doc `docs_blocks`. Short TTLs
  (60 s to 15 m) because these change often.

Each type has its own TTL. Freshness uses the CURRENT configured TTL, not the
value stored when the file was written — lowering a TTL takes effect on
already-written files. A file is expired once its age reaches the TTL.

Invalidation is **local-process only**: another terminal's write isn't visible
until the TTL lapses or you force a refresh. This keeps the model simple at the
cost of cross-process freshness.

## Escape hatches (on any cached read)

    mondo board get 123 --no-cache        # skip cache entirely for this call
    mondo board get 123 --refresh-cache   # force a live refetch + rewrite

`--no-cache` and `--refresh-cache` together are a usage error. Cached reads may
print `cache: hit (entity=…, age=…)` to stderr; silence it with
`MONDO_NO_CACHE_NOTICE=1`. Filtered `item list` variants, account-wide
`update list`, and raw `mondo graphql` are never cached.

## Managing the cache

    mondo cache status [<type>]              # age / freshness / entry count per file
    mondo cache refresh [<type>] [--board ID ...]
    mondo cache clear   [<type>] [--board ID ...] [--stale]

`<type>` is one of: boards, workspaces, users, teams, docs, folders, tags,
webhooks, columns, groups, board_details, items, board_items, subitems,
updates, docs_blocks, or `all` (the default).

**status** prints one row per file with `fresh` (servable now) and `stale` (a
file that exists but has aged past its TTL — reclaimable). A cold type shows
both false. In table output a footer nudges you to `cache clear --stale` when
anything is stale. Project the reclaimable set with:

    mondo cache status -q "[?stale].path"

**clear** soft-deletes cache files (idempotent).

    mondo cache clear --stale        # remove ONLY expired files; keep fresh ones
    mondo cache clear                # remove everything
    mondo cache clear columns --board 42

`--stale` is endpoint- and schema-aware: files written against a different
monday endpoint (kept intentionally for when you switch back) and wrong-schema
files (self-healed on next read) are never reclaimed. Plain `clear` removes
regardless of age. `--board` applies only to `columns`/`groups`/`webhooks`/
`board_details`.

**refresh** force-refetches and rewrites. The per-item / per-doc caches
(`items`, `board_items`, `subitems`, `updates`, `docs_blocks`) can't be
refreshed here — each needs a specific id — so use the read command's
`--refresh-cache` instead (e.g. `mondo item get 999 --refresh-cache`).

All three honor `--profile` and preview with `--dry-run`.
