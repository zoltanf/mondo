# Entity directory cache — design spec

Date: 2026-04-20
Status: design approved, awaiting implementation plan
Scope: phase A (list-command transparent cache + fuzzy name search)
Out of scope: phase B (name→ID resolver, `<entity> find` commands, negative-lookup refresh)

## 1. Problem

The monday.com GraphQL API is slow, and `mondo`'s list commands for boards,
workspaces, users, and teams have no server-side name filter. `mondo board list
--name-contains foo` walks the entire boards collection (100 per page) every
invocation, even though the directory of boards changes rarely. Repeated
interactive use and agent pipelines pay this cost over and over.

## 2. Goal

Cache the slowly-changing *directory* (id, name, a handful of static metadata
fields) for boards, workspaces, users, and teams on local disk, and serve
filtered `list` queries from the cache. Add fuzzy name matching as a natural
follow-on since the full directory is already resident.

This is a **performance optimization**, not a data store. Any cache-path
failure degrades silently to the live API path.

## 3. Non-goals

- Caching item-level data (`items_page`, column values, activity logs, updates).
- Cross-process locking.
- Background or pre-emptive refresh.
- Negative-lookup cache-miss refresh (deferred to phase B).
- `mondo <entity> find` name-resolution commands (deferred to phase B).
- Caching `items_count` on boards (too volatile).
- Detecting writes made by other processes / users / clients (only same-process
  mutations invalidate; other changes are picked up at TTL expiry or manual
  refresh).

## 4. Scope

Entity types covered:

- **boards**
- **workspaces**
- **users**
- **teams**

Commands affected:

- `mondo board list`, `mondo workspace list`, `mondo user list`, `mondo team list`
  — gain cache-backed serving plus new flags (see §8).
- `mondo board create/update/archive/delete/duplicate` — add post-success cache
  invalidation for `boards.json`. Analogous invalidation for workspace/user/team
  mutations where those exist.
- New command group: `mondo cache status/refresh/clear` (see §9).

## 5. Architecture & module layout

New package `mondo/cache/`:

- `mondo/cache/paths.py` — XDG resolution
  (`$XDG_CACHE_HOME/mondo/<profile>/`, fallback `~/.cache/mondo/<profile>/`,
  env override `MONDO_CACHE_DIR`).
- `mondo/cache/store.py` — `CacheStore(entity_type, profile, api_endpoint,
  cache_dir)` handles load/save/invalidate for one entity type. Methods:
  `read() -> CachedDirectory | None`, `write(entries)`, `invalidate()`,
  `age() -> timedelta | None`, `path: Path`.
- `mondo/cache/directory.py` — `get_boards(client, opts)`, `get_workspaces(...)`,
  `get_users(...)`, `get_teams(...)`. Each consults its `CacheStore`, validates
  freshness + endpoint match, returns cached entries or fetches live and
  populates.
- `mondo/cache/fuzzy.py` — `fuzzy_score(query, entries, threshold=70) ->
  list[tuple[entry, score]]`, wrapping `rapidfuzz.process.extract`, sorted
  descending by score.

Separation rationale: `store.py` knows nothing about monday or GraphQL — it
just reads and writes JSON envelopes with TTL checks. `directory.py` owns
fetch-or-serve-from-cache orchestration. `fuzzy.py` is isolated and swappable.

**New dependency**: `rapidfuzz` (MIT-licensed C-extension; ~2 MB wheel). Added
to `pyproject.toml` runtime dependencies.

## 6. Storage format

**Location**: `$XDG_CACHE_HOME/mondo/<profile>/` (fallback `~/.cache/mondo/<profile>/`).
Env override: `MONDO_CACHE_DIR`. Directory created lazily on first write with
mode `0700`. Files created with mode `0600`.

**Files**: `boards.json`, `workspaces.json`, `users.json`, `teams.json`.

**Envelope**:

```json
{
  "schema_version": 1,
  "fetched_at": "2026-04-20T10:15:00Z",
  "ttl_seconds": 28800,
  "api_endpoint": "https://api.monday.com/v2",
  "mondo_version": "0.3.1",
  "count": 342,
  "entries": [ { ... }, ... ]
}
```

**Freshness check on read** (all must pass; any miss → treat as cold):

- `schema_version == 1`
- `now - fetched_at < ttl_seconds`
- `api_endpoint` equals the current profile's endpoint

`mondo_version` is informational only — not a freshness signal.

**Writes are atomic**: write `boards.json.tmp`, `os.replace()` onto
`boards.json`. No flock. Two concurrent writers → both fetch, last `os.replace`
wins. Both callers return correct data.

**Corrupt file** (unparseable JSON, missing fields, wrong schema_version):
log DEBUG, delete the file, behave as cold cache. No error surfaced.

**Write failure** (permission / disk full): log WARNING, serve the
freshly-fetched entries from memory for the current invocation, do not raise.

## 7. Cached schema

All entries hold only the static directory metadata — fields that change on
human timescales, not per-item-edit.

- **boards** — `id`, `name`, `description`, `state`, `board_kind`,
  `board_folder_id`, `workspace_id`, `updated_at`. **Not** `items_count`
  (volatile; bypasses cache when requested).
- **workspaces** — `id`, `name`, `kind`, `description`.
- **users** — `id`, `name`, `email`, `enabled`, `is_admin`, `is_guest`.
- **teams** — `id`, `name`, `picture_url` (confirm against the current
  `mondo team list` field set during planning).

**Cache-fill strategy**: on cold or expired cache, fetch the entire directory
unfiltered (no `--state`, `--kind`, `--workspace`), including archived boards.
One-time cost per TTL window; every subsequent filter is free for the TTL
window.

## 8. Integration with `list` commands

Four commands route through `mondo/cache/directory.py`: `board list`,
`workspace list`, `user list`, `team list`.

### 8.1 New flags (added to each of the four commands)

- `--name-fuzzy TEXT` — fuzzy filter on name. Mutually exclusive with
  `--name-contains` and `--name-matches` (extends existing mutex check).
- `--fuzzy-threshold INT` (default 70, range 0–100) — minimum rapidfuzz score
  to include.
- `--fuzzy-score` (bool, default off) — when set, output includes a
  `_fuzzy_score` field per entry and results are sorted by score descending.
  When off, fuzzy filters but result order follows `--order-by`.
- `--no-cache` — skip cache for this run (live fetch, no cache write).
- `--refresh-cache` — force refresh before serving (live fetch + cache write).

`--no-cache` and `--refresh-cache` together → usage error (exit 2).

### 8.2 Serving logic

1. Resolve cache path for entity type + profile.
2. Read envelope. If fresh + endpoint-match + schema-match: go to step 4.
3. Live-fetch unfiltered directory, write cache, use result.
4. Apply client-side filters in order: `--state`, `--kind`, `--workspace`,
   `--name-*`, `--order-by`, `--max-items`.
5. Emit via `opts.emit(...)`.

### 8.3 Cache bypass

| Flag | Behavior |
|---|---|
| `--no-cache` | Live fetch using today's code path (`iter_boards_page` with server-side filters where supported). Cache untouched. |
| `--with-item-counts` | Bypasses cache — not cached; live fetch. |
| `--refresh-cache` | Live fetch of unfiltered directory, cache written, then filter. |

### 8.4 Write invalidation

After a successful `board create/update/archive/delete/duplicate` the command
calls `CacheStore(entity_type="boards", ...).invalidate()` in a `finally`
block. Failure paths (raised `MondoError`) do not invalidate. Analogous hook
points exist for any existing workspace/user/team mutations.

### 8.5 Help / epilog examples

New entries added to `mondo/cli/_examples.py` for:

- `--name-fuzzy` usage on each list command
- `--refresh-cache` / `--no-cache` usage
- `mondo cache status/refresh/clear`

These flow automatically into `mondo help` and `mondo help --dump-spec` output.

## 9. `mondo cache` command group

```
mondo cache status  [--profile <name>]
mondo cache refresh [<type>] [--profile <name>]
mondo cache clear   [<type>] [--profile <name>]
```

`<type>` ∈ `boards | workspaces | users | teams | all`. Default: `all`.
Unknown `<type>` → usage error (exit 2).

### 9.1 `mondo cache status`

Emits one row per entity type: type, path, fetched_at, age, ttl, fresh (bool),
entry count. Supports the global `--output` flag (table default, json/jsonc/
yaml also valid). Read-only — dry-run is a no-op.

### 9.2 `mondo cache refresh [type]`

Force-fetches the specified type(s) and writes the cache. Same code path as
`--refresh-cache` on list commands. Emits per-type `{type, fetched_at, count}`.
Honors `--dry-run` (emits the fetch plan without executing).

### 9.3 `mondo cache clear [type]`

Deletes cache file(s) for the specified type(s). Idempotent — missing files
are not errors. Emits per-file `{type, path, removed: bool}`. Honors
`--dry-run`.

### 9.4 Profile scoping

All three commands honor the existing global `--profile` flag. Act on the
resolved profile's cache directory. A `--all-profiles` flag is out of scope
for this spec.

## 10. Config additions

New optional `cache:` section. All fields have defaults; no change required
for existing configs.

### 10.1 Global level

```yaml
cache:
  enabled: true               # master switch; false = never consult or write cache
  dir: null                   # override XDG path; null = default
  ttl:
    boards: 28800             # 8h
    workspaces: 86400         # 24h
    users: 86400              # 24h
    teams: 86400              # 24h
  fuzzy:
    threshold: 70             # default --fuzzy-threshold if not passed on CLI
```

### 10.2 Per-profile override (same shape, merges onto global)

```yaml
profiles:
  acme:
    api_token_keyring: acme:token
    cache:
      ttl:
        boards: 3600          # this profile wants fresher boards
```

### 10.3 Env-var overrides (highest-precedence non-CLI source)

- `MONDO_CACHE_ENABLED` — `true|false|0|1`
- `MONDO_CACHE_DIR` — absolute path
- `MONDO_CACHE_TTL_BOARDS`, `MONDO_CACHE_TTL_WORKSPACES`,
  `MONDO_CACHE_TTL_USERS`, `MONDO_CACHE_TTL_TEAMS` — integer seconds
- `MONDO_CACHE_FUZZY_THRESHOLD` — integer 0–100

### 10.4 Precedence (lowest → highest)

1. Built-in defaults (listed above)
2. Global `cache:` block
3. Profile-level `cache:` block (merges key-by-key onto global)
4. Env vars
5. CLI flags (`--no-cache`, `--refresh-cache`, `--fuzzy-threshold`)

### 10.5 Schema implementation

New `CacheConfig` and `CacheTTLConfig` and `CacheFuzzyConfig` Pydantic models
in `mondo/config/schema.py`, both `extra="forbid"`. Added as optional fields
on both `Config` and `Profile`. Merge logic lives in a new
`resolve_cache_config(config, profile_name, env)` helper (not inside
`Profile.get_profile` — keeps that method's single-purpose shape).

### 10.6 First-run

With no config file present: cache enabled with built-in defaults. No prompts.

## 11. Error handling & failure modes

The cache is a performance layer. Any failure degrades silently to the live
path.

| Situation | Behavior |
|---|---|
| Cache file doesn't exist | Cold → live fetch, write cache. |
| Unparseable / wrong schema_version / missing fields | Log DEBUG, delete file, treat as cold. |
| Present but expired | Live fetch, overwrite cache. |
| `api_endpoint` mismatch | Treat as cold. |
| Cache dir not writable | Serve from memory, log WARNING once per invocation. |
| Atomic rename fails | Log WARNING, continue serving fetched data. |
| Concurrent refresh by two processes | Both fetch; last `os.replace` wins. Both return correct data. |
| `--no-cache` + `--refresh-cache` | Usage error (exit 2). |
| `--name-fuzzy` + `--name-contains` / `--name-matches` | Usage error (exit 2) — extends existing check. |
| `rapidfuzz` import fails | Clean `MondoError` on `--name-fuzzy` use only. Non-fuzzy paths unaffected. |
| `mondo cache clear` with no files | Idempotent success (exit 0). |
| Network failure on refresh | `MondoError` propagates. Stale cache is NOT served as a fallback. |

**Logging**: cache events go through existing `loguru`:
- DEBUG: hits, misses, expiry, write success, corrupt-file deletion
- WARNING: write failures

No INFO-level spam on happy path.

**Security**: cache dir `0700`, files `0600`. Envelopes contain only data the
user already fetched with their own token — no additional secrets. Token
redaction continues to work via `mondo.logging_.register_secret`.

## 12. Testing strategy

Unit tests (new files in `tests/unit/`):

- `test_cache_store.py` — read/write/invalidate, corrupt-file recovery, atomic
  rename, endpoint mismatch, TTL expiry (frozen time via `freezegun` or
  `monkeypatch` on `datetime.now`), file mode `0600`, dir mode `0700`.
- `test_cache_directory.py` — fetch-on-miss, serve-on-hit, fetch-on-expiry,
  write-invalidation via mutation hooks. Uses a `FakeMondayClient` pattern
  consistent with existing `tests/unit/test_cli_*` tests.
- `test_cache_fuzzy.py` — threshold filtering, ordering, `--fuzzy-score`
  output shape, empty-query behavior, missing `rapidfuzz` fallback.
- `test_cli_cache.py` — `cache status / refresh / clear` output shapes (table
  and json), dry-run behavior, per-type selection, unknown `<type>` → exit 2,
  profile scoping.

Extensions to existing files:

- `test_cli_board.py` (+ `test_cli_workspace.py`, `test_cli_user.py`,
  `test_cli_team.py`) — `--no-cache`, `--refresh-cache`, `--name-fuzzy`,
  cache bypass under `--with-item-counts`, invalidation on mutation.
- `test_config_schema.py` / `test_config_loader.py` — new `cache:` section,
  env-var overrides, profile-level merge, precedence chain.

Integration tests (`tests/integration/`) follow existing patterns and are
scoped separately.

## 13. Documentation

### 13.1 New document: `docs/caching.md`

Canonical reference covering:

- Overview (what's cached, why, what's NOT cached)
- Storage format, location, envelope shape, atomic-write guarantees
- TTL defaults + precedence chain
- Filter routing table (cache vs bypass)
- `--name-fuzzy`, `--fuzzy-threshold`, `--fuzzy-score`
- `mondo cache status / refresh / clear` usage + examples
- Invalidation model (TTL + same-process write-invalidation; other writers
  only picked up at TTL expiry or manual refresh)
- Failure modes + observable behavior
- Non-goals
- Forward pointer to future phase-B doc (name→ID resolution)

### 13.2 Touched documents

- `docs/plan.md` — add a "Phase 4 (caching)" bullet in the roadmap,
  link to `docs/caching.md`.
- `docs/monday-api.md` — in the `boards` / pagination section, add a short
  note pointing to `docs/caching.md` for client-side read perf. No duplication.
- `docs/help-system.md` — note that new `mondo cache` group, `--name-fuzzy`,
  `--no-cache`, and `--refresh-cache` are registered in `_examples.py` and
  surface via `mondo help` / `mondo help --dump-spec` like every other command.
- `README.md` — add "cache" to the existing feature list in the status
  paragraph; add a brief "## Caching" subsection (3–5 lines) pointing to
  `docs/caching.md`.

### 13.3 Not touched

- `implementation-phase-{1,2,3}.md` — historical records.
- `project codename mondo.md` — vision-level, not feature-level.

## 14. Rollout & compatibility

- Feature is enabled by default; `cache.enabled: false` in config or
  `MONDO_CACHE_ENABLED=false` disables it globally.
- No schema migration needed: existing configs without a `cache:` section
  pick up built-in defaults.
- Existing `mondo board list` / `workspace list` / `user list` / `team list`
  output shape is preserved. Cached serves return the same fields as live
  serves (minus `items_count` when not requested).
- `--no-cache` gives users an explicit escape hatch to reproduce pre-cache
  behavior for debugging.
