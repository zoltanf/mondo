# mondo · Phase 3 Implementation Summary

**Tag:** `v0.3.0` · **Date:** 2026-04-19 · **Status:** Phase 3 complete. The
full roadmap from `plan.md` has shipped. All 655 unit tests green; ruff +
mypy strict clean. Not yet live-verified against a real monday.com account
(unit-tested only).

Phase 3 is the broad tail of the monday API — everything that wasn't
items/columns (Phase 1) or structural board/group/workspace + export/import
+ complexity (Phase 2). Nine sub-phases cover users, teams, subitems,
updates, workspace docs, webhooks, files, activity logs, folders, favorites,
tags, notifications, aggregations, validation rules, and me/account.

---

## 1. What shipped

### Command surface (Phase 3 additions only)

```
mondo user        list | get | deactivate | activate | update-role |
                  add-to-team | remove-from-team
mondo team        list | get | create | delete |
                  add-users | remove-users | assign-owners | remove-owners
mondo subitem     list | get | create | rename | move | archive | delete
mondo update      list | get | create | reply | edit | delete |
                  like | unlike | clear | pin | unpin
mondo doc         list | get | create | add-block | add-content |
                  update-block | delete-block
mondo webhook     list | create | delete
mondo file        upload | download
mondo folder      list | get | create | update | delete
mondo tag         list | get | create-or-get
mondo favorite    list
mondo activity    board
mondo notify      send
mondo aggregate   board
mondo validation  list | create | update | delete
mondo me
mondo account
```

Complete top-level command list after v0.3.0 (25 groups):

```
auth  item  subitem  update  column  group  board  workspace  user  team
doc   webhook  file  folder  tag  favorite  activity  notify  aggregate
validation  me  account  export  import  complexity  graphql
```

### Numbers

| Metric | Before (v0.2.0) | After (v0.3.0) | Δ |
|---|---:|---:|---:|
| Tests (unit) | 525 | **655** | +130 |
| Source files (src/mondo) | 53 | **68** | +15 |
| Test files (tests/unit) | 34 | **43** | +9 |
| Source LoC (src/mondo) | ~7,210 | ~11,355 | +4,145 |
| Test LoC (tests/unit) | ~5,966 | ~8,578 | +2,612 |
| Commits on main | 14 | **23** | +9 (3a–3i) |
| Top-level command groups | 12 | **25** | +13 |
| Runtime dependencies | 9 | 9 | — |
| Python target | 3.14 | 3.14 | — |
| Lint / types | ruff + mypy strict, clean | ruff + mypy strict, clean | — |

---

## 2. Architecture

New and notable files in Phase 3 (all additions — no Phase 1/2 file shed):

```
src/mondo/
├── cli/                      # Typer command groups
│   ├── main.py               # now mounts 21 sub-apps + 4 top-level commands
│   │
│   ├── user.py               # NEW 3a — 7 subcommands, dispatches 4 role mutations
│   ├── team.py               # NEW 3b — 8 subcommands, CreateTeamAttributesInput
│   ├── subitem.py            # NEW 3c — 7 subcommands, codec dispatch via
│   │                         #          --subitems-board preflight
│   ├── update.py             # NEW 3d — 11 subcommands, HTML body, page cap 100
│   ├── doc.py                # NEW 3e — 7 subcommands, reuses markdown↔blocks
│   ├── webhook.py            # NEW 3f — 3 subcommands
│   ├── file.py               # NEW 3g — upload/download; multipart to /v2/file
│   │
│   ├── activity.py           # NEW 3h — nested-only activity_logs iterator
│   ├── folder.py             # NEW 3h — 5 subcommands, folder CRUD
│   ├── favorite.py           # NEW 3h — read-only (add/remove deferred)
│   ├── tag.py                # NEW 3h — 3 subcommands
│   │
│   ├── notify.py             # NEW 3i — create_notification
│   ├── me.py                 # NEW 3i — top-level `me` + `account` commands
│   ├── aggregate.py          # NEW 3i — 2026-01 Aggregation API
│   └── validation.py         # NEW 3i — server-side validation rules
│
├── api/
│   ├── client.py             # +upload_file() method — multipart /v2/file
│   ├── queries.py            # +46 queries/mutations across 3a–3i
│   └── (other files unchanged)
└── (other packages unchanged)
```

### Data flow — file upload (new in 3g)

```
mondo file upload --file report.pdf --item 42 --column files
 └→ cli.argv.reorder_argv
   └→ root callback → GlobalOpts
     └→ cli.file.upload_cmd
       ├─ pick query by --target (FILE_UPLOAD_ITEM vs FILE_UPLOAD_UPDATE)
       ├─ validate required fields for the target
       ├─ build_client()
       └─ client.upload_file(query, variables, file_path):
            ├─ POST /v2/file  (NOT /v2)
            ├─ form data: {"query": ..., "variables": json, "map": {"file":"variables.file"}}
            ├─ files: {"file": (basename, binary)}
            ├─ Content-Type: multipart/form-data  ← set by httpx, NOT by us
            └─ returns {data: {add_file_to_column: {id, name, url, ...}}}
       └─ opts.emit(data.add_file_to_column)
```

### Data flow — aggregate with --select parsing (new in 3i)

```
mondo aggregate board --board 42 --group-by status --select "SUM:price" --select "COUNT:*"
 └→ _parse_select(["SUM:price","COUNT:*"]):
     ├─ "SUM:price"  → {"function": "SUM", "column_id": "price"}
     └─ "COUNT:*"    → {"function": "COUNT"}                          (no column_id key)
 └→ _parse_group_by(["status"]) → [{"column_id": "status"}]
 └→ client.execute(AGGREGATE_BOARD, {board, groupBy, select, rules, limit})
 └→ opts.emit(data.aggregate)                                          (AggregateGroupByResult[])
```

---

## 3. Sub-phase history

| Sub-phase | Scope | Commit | +Tests |
|---|---|---|---:|
| **3a** | User CRUD — `list / get / activate / deactivate / update-role / add-to-team / remove-from-team`. `--role` dispatches to one of four mutations (admins/members/guests/viewers) — monday has no role-enum argument. Deactivate prompts; mass mutations return partial-success shapes. | `0496aff` | 15 |
| **3b** | Team CRUD — `list / get / create / delete + add-users / remove-users / assign-owners / remove-owners`. `create_team(input, options)` takes `CreateTeamAttributesInput`; `delete --hard` required. Partial-success `{successful_users, failed_users}` for all mass-change mutations. | `f4b523f` | 12 |
| **3c** | Subitem CRUD — `list / get / create / rename / move / archive / delete`. Subitems live on a hidden board (§12); `create` supports optional `--subitems-board` for codec dispatch on `--column` values. Rename/move/archive/delete reuse item mutations against the subitem's own ID. | `00d8406` | 13 |
| **3d** | Item updates (comments) — `list / get / create / reply / edit / delete / like / unlike / clear / pin / unpin`. Body is **HTML** (not markdown, §13); help text calls this out. `list --item` paginates via nested items{updates} (100-cap); `list` without `--item` uses the root `updates` query. `create/reply/edit` share a `--body / --from-file / --from-stdin` resolver. | `41c9943` | 18 |
| **3e** | Workspace docs — `list / get / create / add-block / add-content / update-block / delete-block`. Distinct from the `doc` *column* type. `get` supports `--id` or `--object-id` (exactly one) and `--format markdown`. `add-content` reuses the Phase-1f `markdown_to_blocks` converter. No top-level delete — monday has no `delete_doc` mutation. | `6e36b82` | 16 |
| **3f** | Webhooks — `list / create / delete`. `--config` is JSON-validated client-side. monday's one-time challenge handshake happens on the user's endpoint; mondo just fires the mutation and surfaces errors. | `203a362` | 7 |
| **3g** | Files — `upload / download`. New `MondayClient.upload_file()` method posts multipart to `/v2/file` (NOT `/v2`) with the GraphQL-multipart-request-spec form layout. `download` fetches the pre-signed URL via `assets(ids)` then streams bytes to disk. | `e55388d` | 9 |
| **3h** | Activity + folders + favorites + tags — 4 new sub-apps bundled. `activity board` paginates nested `activity_logs`; `folder` is full CRUD (update requires ≥1 attr; position accepts JSON); `favorite list` is read-only (add/remove deferred pending SDL verification); `tag` is list/get/create-or-get against the existing Phase-1e mutation. | `af65e73` | 21 |
| **3i** | Notify + me/account + aggregate + validation (release) — `notify send` (single-user per monday's API); `me` / `account` as top-level commands (no sub-app since each is a single query); `aggregate board` with a `FUNCTION:COL` parser for `--select`; `validation list/create/update/delete` with JSON-validated values. Version bumped to 0.3.0. | `1bf4db4` | 19 |

Total: **9 commits, 130 new tests**, zero regressions.

---

## 4. Key design decisions

### 4.1 Role enum hides four distinct mutations
monday exposes four mutations — `update_multiple_users_as_admins`,
`_members`, `_guests`, `_viewers` — with identical shapes but different
names. `mondo user update-role --role admin|member|guest|viewer` maps
each value to its mutation through a `_ROLE_TO_MUTATION` dict. Users
get a single ergonomic command; the dispatch is a two-field tuple
lookup (query, response-key).

### 4.2 Partial-success payloads passed through verbatim
Mass-change mutations (`add_users_to_team`, `deactivate_users`, etc.)
return `{successful_users, failed_users}` so callers can retry only the
failures. mondo surfaces the whole envelope — we don't flatten, re-
shape, or silently drop errors. Agents can JMESPath into
`failed_users[].message` for fine-grained retry logic.

### 4.3 Subitem codec dispatch is opt-in via `--subitems-board`
Subitems have their own hidden board with its own column IDs. Without
an extra query, we can't know those IDs for codec dispatch. Rather
than force a preflight, `subitem create` treats `--column K=V` as raw
by default. Pass `--subitems-board <id>` (easily discovered via
`mondo subitem list --parent <id>` → `.[0].board.id`) to enable codec
dispatch. Pay-what-you-use.

### 4.4 Rename/move/archive/delete for subitems reuse item mutations
Subitems are `Item`s at the GraphQL level. Rather than duplicate the
Phase-1d mutation queries under subitem-specific names, `subitem
rename/move/archive/delete` reimports and reuses `ITEM_RENAME /
ITEM_MOVE_GROUP / ITEM_ARCHIVE / ITEM_DELETE`. The command group exists
for discoverability and consistency; the wire is shared.

### 4.5 Update body is HTML, documented loudly
monday's update body takes HTML (`<p>`, `<mention>`, inline `<a>`). A
markdown input would be silently misrendered. `mondo update create`
help text opens with "HTML — monday does not accept markdown" so users
who have markdown would know immediately. We don't convert; that's a
future `--markdown` flag.

### 4.6 Pagination for single-item updates is inlined, not via helper
`mondo update list --item` can't use `iter_boards_page` because the
shape is nested (`items[0].updates[]`, not `updates[]` at the top
level). We inlined a small while-loop instead of extending the helper
with a nested-selector parameter; simpler to read, one-off path, and
terminates on a short page the same way.

### 4.7 Workspace docs reuse the Phase-1f markdown converter
`mondo doc add-content --doc <id> --from-file spec.md` calls
`mondo.docs.markdown_to_blocks(md)` — the exact parser written in 1f for
the `doc` column type. One converter, two callers (column-level and
workspace-level docs). Block types are headings h1–h3, paragraphs,
bulleted / numbered lists, blockquotes, fenced code, horizontal rules.

### 4.8 Webhook challenge handshake is the user's problem
monday's `create_webhook` does a one-time POST of `{"challenge":"..."}`
to the user's URL; the endpoint must echo it back within a window or
creation fails. mondo isn't a server — we post the mutation and let
monday's error surface if the echo is missing. Help text explains this
up front.

### 4.9 Files: multipart against `/v2/file`, bytes streamed for download
Upload uses the GraphQL multipart request convention (variables: `{file:
null}` + map: `{"file":"variables.file"}`). New
`MondayClient.upload_file()` method doesn't reuse `execute()` because the
protocol differs. Do NOT set `Content-Type` — httpx picks the boundary.
Download fetches the pre-signed URL via `assets(ids)` and streams the
body chunk-by-chunk via `httpx.stream(...)` — no 500 MB in memory.

### 4.10 Activity logs pagination inline, same pattern as update list
Activity logs are nested under `boards { activity_logs }`, not a root
query. `mondo activity board` uses the same inlined page-based while-
loop as `mondo update list --item`. Filter arguments (user/item/group/
column IDs, from/to) travel through every page request.

### 4.11 Favorites: read-only by design (for now)
monday-api.md §14 mentions "Mutations to add/remove" without
spellings. Rather than ship broken stubs that wouldn't survive a live
call, Phase 3h shipped only `favorite list`. Add/remove is queued
pending live SDL introspection (planned in the Phase 3 follow-up cycle
alongside live verification). Documented as such in the help text and
README.

### 4.12 `mondo notify send` is single-user per monday's API
`create_notification` accepts one user per call; mondo mirrors that
instead of inventing a batched interface that would loop client-side.
Shell loops (or a `mondo graphql` batch) handle multi-user. The
`internal` flag is boolean, sent as `None` when off (monday treats a
missing value the same as false, but passing `false` explicitly
triggers a deprecation warning on some API versions).

### 4.13 `mondo me` / `mondo account` are top-level commands, not sub-apps
Each resolves to a single query with no flags. A sub-app with a single
subcommand would force the user to type `mondo me status` or similar —
needless ceremony. They're registered via `app.command(...)` instead
of `app.add_typer(...)`.

### 4.14 Aggregate `--select FUNCTION:COL` parser, not raw JSON
The raw `SelectInput[]` shape is `[{function: SUM, column_id: "price"}]`
— cumbersome on the command line. The `FUNCTION:COL` shorthand
(`--select SUM:price`, `--select COUNT:*`) covers every practical
aggregation with minimal typing. `*` means "no column_id" (count all).
Validation against the `_SELECT_FUNCTIONS` set rejects typos at parse
time with a clear error.

### 4.15 Validation value is JSON, not structured flags
Validation rules are heterogeneous (`REQUIRED`, `MIN_VALUE`,
`MAX_LENGTH`, regex patterns, …) and each type's `value` shape is
independent. Rather than guess per-type flags, `validation create
--value '<json>'` accepts the full JSON shape directly; the CLI
validates it's valid JSON and passes it through. `--rule-type` is a
free-form string (not an enum) because monday periodically adds new
rule types.

---

## 5. Quirks discovered during Phase 3

| # | Discovery | Fix |
|---|---|---|
| 1 | monday exposes **four** role-change mutations (`update_multiple_users_as_admins/members/guests/viewers`) with identical shapes. No single role-enum mutation. | `_ROLE_TO_MUTATION` dict in `cli/user.py`; `UserRole` enum on the CLI side maps to (query, response_key) tuples. |
| 2 | `create_team(input, options)` takes a `CreateTeamAttributesInput` object — unlike the sibling mutations that take flat arguments. | Built the attrs dict from multiple optional flags; `--allow-empty` goes in `options`, not `input`. |
| 3 | Subitems are `Item`s but their column IDs live on a different (hidden) board. Codec dispatch needs that board's ID. | `subitem create` takes optional `--subitems-board <id>` to opt into codec dispatch; discovered via `subitem list` → `.[0].board.id`. |
| 4 | `csv.DictReader` skipping blank lines bit us again (Phase 2 quirk #4) in a subitem tests fixture. | Reused the Phase-2 fix: multi-column CSVs so blank-name rows stay non-blank overall. |
| 5 | monday's update `body` takes **HTML**, not markdown. Passing markdown silently renders the raw text. | Help text, README, and the implementation summary all call this out at the top of the `update` section. |
| 6 | `create_update(parent_id:)` toggles between top-level and reply based on whether `parent_id` is set; same mutation, different semantics. | `mondo update create` (parent_id=None) and `mondo update reply` (parent_id required) both route through `UPDATE_CREATE`. Two commands, one mutation — clearer at the CLI surface. |
| 6 | `ruff format` relocated the newly-introduced `_json_dumps` / `_basename` helpers below existing imports, moving the imports below — triggering E402 "import not at top of file". | Consolidated imports first, helper defs after. (Same shape as Phase 1 quirk #1 / Phase 2 import layout.) |
| 7 | Workspace docs have no top-level `delete_doc` mutation — only per-block deletion. | `mondo doc` ships `delete-block`, not `delete`; README calls out that whole-doc deletion is UI-only. |
| 8 | monday webhook event types include `change_subitem_column_value` (spaces → underscores); easy to typo. | Full event catalog in the README's "Webhooks" section copy-pasted from §14. |
| 9 | `NotificationTargetType` is case-sensitive: `Project` and `Post` (not `PROJECT`/`POST`). | Enum defined with `case_sensitive=True` at the Typer layer; test covers the lowercase-rejection path. |
| 10 | `assets(ids)` returns URLs that are already **pre-signed** — don't try to add auth headers to the GET. | `file download` uses a bare `httpx.stream("GET", url, follow_redirects=True)` with no Authorization. |
| 11 | `create_folder` / `update_folder` accept **enum** strings for color / icon / font_weight (`FolderColor`, `FolderCustomIcon`, `FolderFontWeight`). Passing lowercase or hex fails server-side. | README documents the expected enum names; CLI passes `--color` through as a string (no client-side palette validation). |
| 12 | The monday SDL for favorites add/remove mutations has shifted across API versions — no stable spelling confirmed in `monday-api.md`. | `mondo favorite` is read-only for Phase 3; add/remove deferred to a follow-up after live introspection. |

---

## 6. Exit codes (contract continues unchanged)

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic error (e.g. `update delete` aborted on confirmation; import with ≥1 failed row) |
| 2 | usage error |
| 3 | auth error |
| 4 | rate / complexity exhausted after retries |
| 5 | validation error |
| 6 | not found |
| 7 | network / transport error |

Phase 3 new non-zero-exit sites:
- `user update-role` with an invalid role → 2
- `team delete`, `folder delete`, `validation delete` without `--hard` → 2 (except `validation delete`, which uses confirmation rather than `--hard`)
- `subitem delete` without `--hard` → 2
- `doc get` without exactly one of `--id`/`--object-id` → 2; both → 2
- `doc add-content` on empty markdown input → 5
- `update create`/`reply`/`edit` without any of `--body`/`--from-file`/`--from-stdin` → 2
- `webhook create --config` bad JSON → 2
- `file upload --target item` without both `--item` and `--column` → 2
- `file upload --target update` without `--update` → 2
- `folder update` without any of `--name`/`--color`/`--product-id`/`--position` → 2
- `aggregate board --select` with an unknown function or missing colon → 2
- `validation create --value` / `update --value` bad JSON → 2
- `validation update` without `--value` or `--description` → 2
- `notify send --target-type project` (lowercase) → 2

---

## 7. What's next — follow-ups beyond Phase 3

`plan.md`'s numbered Phase 3 is fully covered. The real work ahead is
production-readiness:

- **Live verification**: Phase 1 paired release with a manual smoke
  run; Phase 2 and 3 haven't had that yet. This should precede the
  next tag (which may be a v0.3.1 post-verification or straight to
  v1.0). Recommended: walk the README command-by-command against a
  throwaway monday account and note any mutation spellings that drift
  from our queries.
- **Favorite add/remove**: introspect monday's live SDL to confirm the
  current spelling of the favorites add/remove mutations, then ship
  `mondo favorite add / remove`.
- **Doc version history (2026-03+)**: `doc_version_history(doc_id, ...)`
  and `doc_version_diff(...)` are new in 2026-03 — add `mondo doc
  history` and `mondo doc diff`.
- **Multi-level boards default (2026-04 RC)**: when `hierarchy_type:
  multi_level` becomes the default, the subitem distinction collapses;
  `mondo subitem` should detect this and emit a deprecation hint.
- **Integration tests** (plan §14): nightly runs against
  `MONDAY_TEST_TOKEN` / `MONDAY_TEST_BOARD_ID`. With 25 command groups
  this is overdue.
- **Contract tests** (plan §14): periodic SDL introspection → compare
  against the queries in `api/queries.py` → fail on any field drift
  before it reaches users.
- **Binary distribution** (plan §15): PyInstaller + homebrew tap +
  curl-pipe-bash installer for v1.0.
- **Optional MCP-server mode** (plan §18 open question #2): `mondo mcp
  serve` that exposes the same command surface as an MCP provider for
  agents — leverages the fact that every mondo command is already a
  typed dataclass-shaped I/O contract.

---

## 8. Testing approach

All 655 tests are `pytest` unit tests using `pytest-httpx` to mock the
`/v2` and `/v2/file` endpoints. Phase 3 added **130 tests** across
**9 new test modules**:

```
tests/unit/
├── test_cli_user.py         # 15 cases (3a)
├── test_cli_team.py         # 12 cases (3b)
├── test_cli_subitem.py      # 13 cases (3c)
├── test_cli_update.py       # 18 cases (3d)
├── test_cli_doc.py          # 16 cases (3e)
├── test_cli_webhook.py      # 7 cases (3f)
├── test_cli_file.py         # 9 cases (3g)
├── test_cli_3h.py           # 21 cases (3h: activity+folder+favorite+tag)
└── test_cli_3i.py           # 19 cases (3i: notify+me/account+aggregate+validation)
```

Coverage highlights:
- **Role dispatch**: each of the four `update-role` values routes to
  the correct mutation name in the emitted query.
- **Codec dispatch**: subitem create with `--subitems-board` fetches
  the preflight columns and feeds the codec registry; without the flag,
  values pass through raw.
- **Input resolvers**: update `--body` / `--from-file` / `--from-stdin`
  mutual exclusivity, doc `--markdown` / `--from-file` / `--from-stdin`.
- **Multipart upload**: test verifies we hit `/v2/file` (not `/v2`)
  **and** the `Content-Type` header starts with `multipart/form-data`.
- **Asset streaming download**: mocks the `assets(ids)` query and the
  pre-signed URL both, verifies bytes land at the expected path.
- **Pagination**: activity logs follow page-based termination on short
  page; updates paginate via nested-items path.
- **Aggregate parser**: `FUNCTION:COL` → SelectInput dicts; invalid
  function and missing colon both exit 2.
- **Validation JSON inputs**: good JSON sent through, bad JSON exits 2.

Integration + contract tests remain queued (plan §14, §16).

---

## 9. Honoring monday API quirks (Phase 3 additions)

Continues from Phase 2 §9:

| Quirk | How Phase 3 handles it |
|---|---|
| Four separate role-change mutations (no role enum) | `_ROLE_TO_MUTATION` in `cli/user.py` dispatches on the `UserRole` enum. |
| `users(emails:)` is case-sensitive | Help text calls this out; the CLI doesn't lowercase the input. |
| `create_team(input, options)` uses an input object (not flat args) | `cli/team.py` builds the attrs dict from optional flags; `--allow-empty` goes in `options`, not `input`. |
| Subitems have independent column IDs (hidden board) | `subitem create --subitems-board <id>` opts into codec dispatch; discoverable via `subitem list`. |
| Subitems are `Item`s on rename/archive/delete/move | `cli/subitem.py` reuses Phase-1d item mutations; no duplicate queries. |
| Update `body` is HTML, not markdown | Help text + README banner. `create/reply/edit` all use the shared `--body`/`--from-file`/`--from-stdin` resolver. |
| Update page cap is 100 (2025-04+) | `MAX_UPDATES_PAGE_SIZE = 100` in `cli/update.py`. |
| `create_update(parent_id:)` toggles top-level vs reply | Two commands (`update create` and `update reply`) route through the same mutation; clearer at the CLI surface. |
| Workspace docs have no `delete_doc` — only per-block | `mondo doc` ships `delete-block`, not `delete`; README documents the whole-doc limitation. |
| Webhook challenge handshake is the user's responsibility | `mondo webhook create` fires the mutation; the help text explains the handshake; mondo surfaces any resulting error. |
| File upload: multipart to `/v2/file`, `Content-Type` set by the HTTP lib | `MondayClient.upload_file()` uses httpx's `files=` parameter; no manual `Content-Type`. |
| Asset download URLs are pre-signed (don't add Authorization) | `httpx.stream("GET", url)` bare — no `_headers()` call for the download path. |
| Activity logs are nested only, 1-week retention non-Enterprise | `cli/activity.py` paginates `boards.activity_logs`; help text notes retention. |
| `favorites` add/remove mutation spellings shift across versions | Phase 3h ships read-only `favorite list`; add/remove queued pending SDL introspection. |
| `create_notification` is single-user per call; returns `id: -1` async | `notify send` documents "loop for batches" in help; we emit monday's raw return. |
| `me.account` is the only way to reach account (no root query) | `mondo account` navigates through `me { account { ... } }`. |
| Aggregate `SelectInput.column_id` absent means "all rows" | `_parse_select("COUNT:*")` omits the `column_id` key. |
| Validation rules unsupported on multi-level subitem boards | Not enforced client-side; server returns a clear error. README documents it. |

---

## 10. Quick-reference install & run

```bash
# Clone and bootstrap
git clone <repo>
cd mondo
uv sync --all-extras

# Authenticate
export MONDAY_API_TOKEN="eyJhbGci..."
uv run mondo auth status

# New in Phase 3
uv run mondo user list --kind non_guests -o table
uv run mondo team list -o table
uv run mondo subitem list --parent 1234567890
uv run mondo update list --item 1234567890 --max-items 50
uv run mondo doc list --workspace 42
uv run mondo webhook list --board 1234567890
uv run mondo file upload --file report.pdf --item 1234567890 --column files
uv run mondo file download --asset 9999 --out report.pdf
uv run mondo activity board --board 1234567890 --since 2026-04-18T00:00:00Z
uv run mondo folder list
uv run mondo tag list
uv run mondo favorite list
uv run mondo notify send --user 42 --target 100 --target-type Project --text "FYI"
uv run mondo aggregate board --board 42 --group-by status --select COUNT:*
uv run mondo validation list --board 42
uv run mondo me
uv run mondo account

# Verify
uv run pytest                              # 655 green
uv run ruff check src tests
uv run mypy src
```

Phase 3 adds **no new runtime dependencies** — everything ships on the
Phase 2 dep set (typer, rich, httpx, jmespath, ruamel.yaml, keyring,
pydantic, loguru, openpyxl). No breaking changes to Phase 1 or Phase 2
commands; all existing tests continue to pass.

---

*Phase 3 complete. Tag: `v0.3.0`. Total commits on main since v0.2.0:
9 (3a → 3i). The plan is fully implemented; follow-ups are live
verification, binary distribution, and selective expansion
(favorite add/remove, doc version history, multi-level board detection).*
