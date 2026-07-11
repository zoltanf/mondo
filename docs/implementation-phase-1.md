# mondo · Phase 1 Implementation Summary

**Tag:** `v0.1.0` · **Date:** 2026-04-18 · **Status:** MVP complete, live-verified against a real monday.com account.

Phase 1 of the [plan](plan.md) — auth, items, columns (including the `doc`
column), raw GraphQL passthrough, output formatters, JMESPath projection,
shell completion, and the az/gh/gam-style global-flag UX.

---

## 1. What shipped

### Command surface

```
mondo [--profile NAME] [--api-token TOKEN] [--api-version YYYY-MM]
      [-o {table|json|jsonc|yaml|tsv|csv|none}] [-q JMESPATH]
      [-v|--verbose] [--debug] [-y|--yes] [--dry-run]
      [-V|--version] <command> [<args>]

mondo auth       login | logout | status | whoami
mondo item       get | list | create | rename | duplicate | archive | delete | move
mondo column     list | get | set | set-many | clear
mondo column doc get | set | append | clear
mondo graphql    '<query or mutation>' [--vars JSON]
```

Global flags work **anywhere** on the command line — `mondo item list --board 42 -o table -q '[].name'`
is equivalent to `mondo -o table -q '[].name' item list --board 42`. A small argv
preprocessor normalizes the order before Typer sees it.

### Numbers

| Metric | Value |
|---|---|
| Tests | **419**, all green |
| Source files | 45 (src/mondo/**) |
| Test files | 20 (tests/unit/**) |
| Total Python LoC | ~8,700 |
| Commits | 7 |
| Dependencies (runtime) | typer, rich, httpx, jmespath, ruamel.yaml, keyring, pydantic, loguru |
| Python target | 3.14 (tested on 3.14.3) |
| Lint / Types | ruff + mypy strict, clean |

---

## 2. Architecture

```
src/mondo/
├── cli/                      # Typer command groups
│   ├── main.py               # root app + global flags callback + main() entry
│   ├── argv.py               # az-style flag-anywhere preprocessor
│   ├── context.py            # GlobalOpts carries parsed flags + lazy build_client()
│   ├── auth.py               # login / logout / status / whoami
│   ├── item.py               # item CRUD + cursor-pagination consumer
│   ├── column.py             # column list / get / set / set-many / clear
│   ├── column_doc.py         # column doc get / set / append / clear
│   └── graphql.py            # raw passthrough
├── api/
│   ├── client.py             # httpx-based MondayClient + retries + error mapping
│   ├── auth.py               # token resolution chain + keyring
│   ├── errors.py             # typed exceptions + exit-code taxonomy
│   ├── pagination.py         # items_page / next_items_page iterator
│   └── queries.py            # all GraphQL query strings (one place)
├── columns/                  # Codec registry — 33 types
│   ├── base.py               # ColumnCodec ABC + registry + clear_payload_for
│   ├── simple.py             # text, long_text, numbers, checkbox, rating, country
│   ├── status.py
│   ├── dropdown.py
│   ├── datelike.py           # date, timeline, week, hour
│   ├── people.py
│   ├── contact.py            # email, phone, link
│   ├── location.py
│   ├── tags.py
│   ├── relation.py           # board_relation, dependency, world_clock
│   └── readonly.py           # mirror, formula, auto_number, item_id, creation_log,
│                             # last_updated, color_picker, progress, time_tracking,
│                             # vote, button, subtasks, file
├── config/
│   ├── schema.py             # pydantic Config + Profile models
│   └── loader.py             # XDG-compliant YAML loader + ${VAR} expansion
├── output/                   # 7 formatters, one module each
│   ├── __init__.py           # registry + auto-detect (table on TTY, json else)
│   ├── table.py              # rich tables (key/value, array-of-objects, nested → <list:N>)
│   ├── json_.py · jsonc.py · yaml_.py · csv_.py · tsv.py · none_.py
│   └── query.py              # JMESPath projection (applied *before* formatting)
├── docs.py                   # Doc column: markdown ↔ monday blocks converter
├── logging_.py               # loguru + token-redaction patcher
├── util/kvparse.py           # --column K=V parser
└── version.py                # __version__ = "0.1.0"
```

### Data flow (typical write)

```
argv
 └→ cli.argv.reorder_argv        ← global flags lifted to the front
   └→ Typer root callback         ← parses globals into GlobalOpts
     └→ subcommand handler        ← e.g. mondo column set
       └→ opts.build_client()     ← token resolution chain → MondayClient
         └→ preflight GraphQL     ← fetch column type + settings_str
         └→ mondo.columns.parse_value
           ├→ StatusCodec.parse(value, settings) ───┐
           └→ (for tags) resolve names via          │
              create_or_get_tag                     │
                                                     ↓
         └→ client.execute(CHANGE_COLUMN_VALUE, vars)
           └→ httpx POST /v2         + retry on rate-limit/complexity
         └→ errors.from_response       ← type-dispatch by extensions.code
         └→ opts.emit(data)            ← JMESPath → formatter → stdout
```

---

## 3. Sub-phase history

| Sub-phase | Scope | Commit |
|---|---|---|
| **1a** | Project scaffold — uv venv on Python 3.14, hatchling build, Typer root, `--version` / `--help`, ruff + mypy + pytest configured | `ae1101f` |
| **1b** | Errors + config + auth + MondayClient + `auth status/whoami/login/logout` + `graphql` passthrough. Swapped gql for raw httpx. | `fece5ba` |
| **1c** | Output formatters (7) + JMESPath projection + `--output/-o` + `--query/-q` + TTY auto-detect | `c80bbd7` |
| **1d** | Item CRUD + cursor pagination (items_page/next_items_page with CursorExpiredError restart) + `--yes` + `--dry-run` globals | `fad4973` |
| **1e** | Column CRUD + ColumnCodec registry for 33 types + tag name resolution via `create_or_get_tag` + codec dispatch wired into `item create` | `48d74aa` |
| **1f** | Doc-column subcommands (get/set/append/clear) + markdown ↔ monday block converter. Live testing exposed monday quirks (block type with spaces, JSON-string content) — both handled. | `6862191` |
| **1g** | Global-flag ordering (az-style), README refresh, live end-to-end verification. This commit. | *(this release)* |

---

## 4. Key design decisions

### 4.1 Raw httpx over `gql`
Plan §3 lists `gql` as the canonical choice but permits raw httpx as "an
acceptable minimalist alternative." We picked httpx because:
- Single endpoint, single JSON envelope — gql's schema-validation is overhead.
- `pytest-httpx` mocks the transport natively — gql would need a fake transport layer.
- Smaller dep tree, faster PyInstaller cold-start (relevant for the future binary distribution).

We kept the error mapping / retry / complexity-aware layers; they sit above
httpx the same way they would above gql.

### 4.2 Plain retry loop over `tenacity`
Plan §8.3 sketches a tenacity-decorated executor. We implemented a ~20-line
loop directly on `MondayClient.execute`:
- Honors monday's `extensions.retry_in_seconds` exactly when present.
- Stops on non-retryable exceptions immediately.
- Injectable `retry_sleep` callable makes tests deterministic (`retry_sleep=lambda _: None`).
- Zero extra dependency.

### 4.3 Codec registry, not class hierarchy
Each column type is a module (`simple.py`, `status.py`, etc.) that registers
a `ColumnCodec` subclass at import time via `register()`. This:
- Makes adding a new type a 30-line patch with its own test module.
- Lets us namespace codecs by domain (date-family together, contact-family together) without a class hierarchy.
- Supports future extension — third parties could `register()` their own codec without patching our code.

### 4.4 Tag name resolution at the CLI layer, not the codec
Codec `parse` is pure (no I/O). But tag names need `create_or_get_tag` round-trips.
Solution: codec rejects names with a clear error; the CLI handler
(`column.py:_resolve_tag_names_to_ids` and `item.py` analog) detects name inputs
before calling the codec, resolves them, and feeds the codec integer IDs.

### 4.5 az-style global-flag ordering via argv preprocessor
Typer/Click's left-to-right parsing rejects root flags after subcommands.
`mondo.cli.argv.reorder_argv` scans argv, pulls recognized globals
(and their values for value-taking flags) to the front, leaves everything
else in place. Covered by 17 regression tests. `main()` is the console-script
entry point that calls the preprocessor then hands off to the Typer app.

### 4.6 `--dry-run` emits the mutation as structured data
Every mutation-shaped command short-circuits before the HTTP call under
`--dry-run`, emitting `{"query": "<mutation>", "variables": {...}}` through
the normal output pipeline. Users can pipe it into `-o json -q '.variables'`
or paste it into the monday API playground to sanity-check.

### 4.7 Preflight + codec dispatch in `item create`
`mondo item create --board 42 --name X --column status=Done` needs to know
`status` is a status column to codec-translate "Done". We do a one-shot
`boards(ids:[...]) { columns { id type settings_str } }` preflight, then
dispatch each `--column` through the matching codec. `--raw-columns` bypasses
the preflight entirely for fully-offline `--dry-run` runs.

### 4.8 Markdown ↔ monday blocks — line-based parser, zero deps
We considered `markdown-it-py` but chose a line-based parser (~100 lines) that
handles headings h1–h3, paragraphs, bulleted / numbered lists, blockquotes,
fenced code (with language), and horizontal rules. Trade-off: no inline
formatting, no tables, no nested lists. Round-trips markdown → blocks →
markdown for the shapes it supports.

---

## 5. Quirks discovered during live testing

| # | Discovery | Fix |
|---|---|---|
| 1 | `-q "..."` / `-o table` don't work after a subcommand (Typer parser limitation). | `argv.reorder_argv` preprocessor. |
| 2 | Env-var-backed `--api-token` made `auth status` display "via flag" when the token actually came from `MONDAY_API_TOKEN`. | Dropped `envvar=` from the flag; the resolution chain in `api.auth` is the single source of truth for provenance. |
| 3 | Ruff 0.15.11 + `target-version = "py314"` rewrites `except (TypeError, ValueError):` into Py2-style `except TypeError, ValueError:`. Python 3.14 silently accepts it but catches only the first type. | Rewrote to use `isinstance` guards or catch `ValueError` alone. Spawned background task to file a ruff issue. |
| 4 | monday returns doc-block `type` field with a **space** — `"normal text"`, not `"normal_text"`. | `_normalize_type()` converts spaces to underscores on read. We still write the canonical underscore form. |
| 5 | monday returns doc-block `content` as a **JSON-encoded string** (not a parsed object). | `_extract_text()` detects and re-parses when it sees a string. |
| 6 | monday's `boards()` query has **no server-side name filter**. | Documented the `graphql + JMESPath` workaround in the README; `mondo board list --name-contains ...` is queued for Phase 2. |

---

## 6. Output formats

Default: `table` when stdout is a TTY, `json` otherwise (az-style auto-detection).

```
table    Rich-rendered; array-of-objects → rows, object → key/value, nested → <list:N>
json     Compact pretty-printed JSON (machine default)
jsonc    Syntax-highlighted JSON for humans on a TTY
yaml     Block-style YAML (ruamel.yaml, safe dump)
csv      RFC-4180; union of top-level keys; nested values JSON-encoded
tsv      Tab-delimited CSV variant
none     Prints scalars bare; drops structured data (useful with `-q` + shell vars)
```

**JMESPath projection** via `--query/-q` is applied *before* formatting, so
`mondo item list --board X -q "[].{id:id,name:name}" -o csv` produces a clean
two-column CSV without `-o` seeing nested junk.

---

## 7. Live-verified capabilities

Against marktguru's monday account (user 37251583, account 14388737, enterprise tier):

- `mondo auth status` — token source, profile, identity ✓
- `mondo auth whoami -q name -o none` — returns bare `"Zoltan Fekete"` ✓
- `mondo graphql 'query { boards(limit:200) { id name } }' -q "data.boards[?contains(name,'Pager')]" -o table` — live board-by-name search ✓
- `mondo item list --board 5094491899 --max-items 5 -o table -q '[].{id:id,name:name,state:state}'` — cursor pagination + projection + table ✓
- `mondo column list --board 5094861043 -o table` — column schema enumeration ✓
- `mondo column get --item <id> --column files --raw` — raw column value read, codec correctly handles unknown `file` type ✓
- `mondo item create --board 5094861043 --name "mondo v0.1.0 E2E smoke test" --column status=Done --column date4=2026-04-18 -o yaml` — preflight + codec dispatch + create, yields `id: 2851334386` ✓
- `mondo item get --id 2851334386 -q '{name,state,columns:column_values[?text].{id,text}}' -o yaml` — read-back confirms status=Done, date4=2026-04-18 ✓
- `mondo column set --item 2851334386 --column status --value "Working on it"` — codec dispatch on a post-create update ✓
- `mondo column get --item 2851334386 --column status` — prints `"Working on it"` (codec-rendered) ✓
- `mondo item archive --id 2851334386 --yes -o yaml` — `state: archived` ✓
- `mondo --dry-run item create --board X --name "..." --column name="..."` — produces correct `{query, variables}` envelope without sending ✓

---

## 8. Exit codes (stable contract for scripts and agents)

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic error |
| 2 | usage error (handled by Typer/Click) |
| 3 | auth error (no token, bad token, insufficient scope) |
| 4 | rate limit / complexity budget after retries exhausted |
| 5 | validation error (bad column value, unknown column id) |
| 6 | not found |
| 7 | network / GraphQL transport error |

---

## 9. What's next (Phase 2 preview)

Phase 2 broadens to structural operations (board/column/group/workspace CRUD)
and moves data around (import/export). Concrete items:

- `mondo board list|get|create|update|archive|delete|duplicate` with
  `--name-contains`/`--name-matches` client-side filters.
- `mondo column create --type status --title "Priority" --defaults '{...}'`
  and `column rename|delete|change-metadata`.
- `mondo group create|rename|duplicate|archive|delete|reorder`.
- `mondo workspace list|get|create|update|delete|add-user|remove-user`.
- `mondo export board <id> --format {csv,json,xlsx,md}` with subitems.
- `mondo import board <id> --from items.csv --mapping config.yaml` for bulk
  item creation with retry and idempotency-guard support.
- Complexity-field injection + session-wide budget meter (deferred from 1b).

Phase 3 covers users/teams, updates, subitems, webhooks, notifications, tags,
file uploads, aggregation API, multi-level boards, and full workspace docs.

---

## 10. Testing approach

- **Unit tests** against `pytest-httpx` mock transport. Every codec has parse
  + render + clear round-trip coverage.
- **End-to-end CLI tests** invoke the Typer app with `CliRunner`, mock the
  monday endpoint, and assert on exit codes + emitted output shape.
- **No integration tests yet** — those are gated on `MONDAY_TEST_TOKEN` /
  `MONDAY_TEST_BOARD_ID` env vars (plan §14). Live verification was done
  manually during development.
- **Snapshot tests** (`syrupy`) and **contract tests** (SDL diff vs a pinned
  API version) are planned for Phase 2 CI.

---

## 11. Honoring monday API quirks (from `monday-api.md` §16)

| Quirk | How mondo handles it |
|---|---|
| `Authorization` header uses raw token, no `Bearer` prefix | `MondayClient._headers()` hard-codes this |
| `column_values` is a **JSON-stringified string**, not a JSON object | All mutations that take `column_values` `json.dumps()` before sending |
| Column IDs are per-board, not globally unique | Every write path fetches the `board_id` from the target item first |
| Status: prefer `{"index": N}` over `{"label": "..."}` | Status codec accepts both (`#1` or `Done`) and passes the index through if the user uses `#N` |
| People/email columns need user IDs, not emails | People codec explicitly rejects `@`-containing tokens with a pointer to `users(emails:...)` |
| Checkbox: `"true"` (string) to check, `null` to uncheck | Checkbox codec hard-coded to this |
| Week column is double-nested | Week codec builds `{"week": {"startDate": "...", "endDate": "..."}}` |
| Root `items(ids:)` with >100 IDs or no IDs is throttled to 1/2min | We paginate via `items_page` everywhere — never hit the rate-limited form |
| `items_page` cursor lifetime is 60 minutes | `iter_items_page` catches `CursorExpiredError` and restarts |
| API versions shift quarterly | Always pinned via `API-Version` header; defaults to `2026-07` (current as of July 2026) |
| Errors carry `extensions.request_id` (since 2025-05) | Every `MondoError` surfaces it in `str(exc)` |
| Idempotency keys not supported | Every mutation has `--dry-run`; `item archive` (reversible) is preferred over `delete` |

---

## 12. Quick-reference install & run

```bash
# Clone and bootstrap
git clone <repo>
cd mondo
uv sync --all-extras

# Authenticate (any one of these):
export MONDAY_API_TOKEN="eyJhbGci..."     # env (one-off)
uv run mondo auth login                    # OS keyring (recommended)
# or edit ~/.config/mondo/config.yaml (multiple profiles)

# Verify
uv run mondo auth status

# Run tests
uv run pytest                              # 419 green
uv run ruff check src tests
uv run mypy src
```

Binary distribution via PyInstaller + Homebrew tap + curl-pipe-bash installer
is queued for the v1.0 release (plan §15).

---

*Phase 1 complete. Tag `v0.1.0`.*
