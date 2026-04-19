# mondo · Phase 2 Implementation Summary

**Tag:** `v0.2.0` (proposed) · **Date:** 2026-04-18 · **Status:** Phase 2 complete, all checks green. Not yet live-verified against a real monday.com account (unit-tested only).

Phase 2 of the [plan](plan.md) broadens the CLI from Phase 1's item/column focus
to structural monday resources (boards, groups, workspaces), adds bulk data
movement (export/import), and ships a production-readiness feature
(complexity metering) that was deferred from Phase 1.

---

## 1. What shipped

### Command surface (Phase 2 additions only)

```
mondo board       list | get | create | update | archive | delete | duplicate
mondo column      create | rename | change-metadata | delete          # structural
mondo group       list | create | rename | update | reorder |
                  duplicate | archive | delete
mondo workspace   list | get | create | update | delete |
                  add-user | remove-user | add-team | remove-team
mondo export      board --format {csv|tsv|json|xlsx|md} [--include-subitems]
mondo import      board --from items.csv [--mapping map.yaml]
                  [--idempotency-name] [--group ID]
mondo complexity  status
```

Full command tree after Phase 2:

```
mondo [globals] <group> <verb> [--flags]

mondo auth        login | logout | status | whoami
mondo item        get | list | create | rename | duplicate | archive | delete | move
mondo column      list | get | set | set-many | clear |
                  create | rename | change-metadata | delete
mondo column doc  get | set | append | clear
mondo board       list | get | create | update | archive | delete | duplicate
mondo group       list | create | rename | update | reorder |
                  duplicate | archive | delete
mondo workspace   list | get | create | update | delete |
                  add-user | remove-user | add-team | remove-team
mondo export      board
mondo import      board
mondo complexity  status
mondo graphql     '<query or mutation>' [--vars JSON]
```

### Numbers

| Metric | Before (v0.1.0) | After (v0.2.0) | Δ |
|---|---:|---:|---:|
| Tests (unit) | 419 | **525** | +106 |
| Source files (src/mondo) | 45 | **53** | +8 |
| Test files (tests/unit) | 20 | **34** | +14 |
| Source LoC (src/mondo) | ~4,100 | ~7,210 | +3,110 |
| Test LoC (tests/unit) | ~4,600 | ~5,966 | +1,370 |
| Commits | 7 (1a–1g) | 14 (7 new — 2a–2g) | +7 |
| Runtime dependencies | 8 | **9** | +1 (openpyxl) |
| Python target | 3.14 | 3.14 | — |
| Lint / types | ruff + mypy strict, clean | ruff + mypy strict, clean | — |

---

## 2. Architecture

New and modified files in Phase 2 are **bold**:

```
src/mondo/
├── cli/                      # Typer command groups
│   ├── main.py               # mounts 5 new sub-apps: board, group, workspace,
│   │                         #                         export, import_, complexity
│   ├── argv.py               # (unchanged) az-style flag-anywhere preprocessor
│   ├── auth.py               # (unchanged)
│   ├── item.py               # (unchanged)
│   ├── column.py             # +4 commands: create/rename/change-metadata/delete
│   ├── column_doc.py         # (unchanged)
│   ├── graphql.py            # now passes `raw=True` — complexity injection
│   │                         #                           skipped for user queries
│   ├── board.py              # NEW — 7 subcommands
│   ├── group.py              # NEW — 8 subcommands, monday palette validation
│   ├── workspace.py          # NEW — 9 subcommands (incl. add/remove user/team)
│   ├── export.py             # NEW — `export board` with 5 formats
│   ├── import_.py            # NEW — `import board` with YAML mapping
│   └── complexity.py         # NEW — `complexity status`
├── api/
│   ├── client.py             # inject_complexity=True by default;
│   │                         # execute() gains `raw` kwarg; meter attached
│   ├── complexity.py         # NEW — inject_complexity_field + ComplexityMeter
│   ├── queries.py            # +27 queries/mutations (boards, groups,
│   │                         # workspaces, structural columns, subitem-aware
│   │                         # items_page variants)
│   ├── pagination.py         # iter_items_page gains query_initial/_next
│   │                         # overrides; new iter_boards_page helper for
│   │                         # page-based endpoints (boards/workspaces/…)
│   ├── errors.py             # (unchanged)
│   └── auth.py               # (unchanged)
├── columns/                  # (unchanged — reused by import_.py)
├── config/                   # (unchanged)
├── output/                   # (unchanged)
├── docs.py                   # (unchanged)
├── logging_.py               # (unchanged)
├── util/kvparse.py           # (unchanged)
└── version.py                # still 0.1.0; bump to 0.2.0 is pending
```

### Data flow — bulk import (new in 2f)

```
mondo import board --board 42 --from items.csv --mapping map.yaml --idempotency-name
 └→ cli.argv.reorder_argv
   └→ root callback → GlobalOpts
     └→ cli.import_.board_cmd
       ├─ load mapping YAML (columns, name_column, group_column)
       ├─ build_client()                           (complexity injected default on)
       ├─ preflight: boards { columns { id title type settings_str } }
       ├─ resolve {csv_header: column_id}          (explicit → title match)
       ├─ if --idempotency-name:
       │   └─ iter_items_page → set<name> (skips duplicates w/o extra round-trip per row)
       ├─ for each row:
       │   ├─ empty name? → failed + continue
       │   ├─ name in existing_names? → skipped + continue
       │   ├─ encode via ColumnCodec registry (tags resolved via create_or_get_tag)
       │   ├─ [dry-run] stash the create_item envelope; else client.execute(CREATE_ITEM)
       │   └─ append result {created|skipped|failed|dry-run}
       └─ emit {summary:{…}, results:[…]} and exit 1 iff any row failed
```

### Data flow — complexity injection (new in 2g)

```
client.execute(query) — called by every CLI write path
 └─ if inject_complexity and not raw:
     query = inject_complexity_field(query)        (idempotent, brace-matching)
 └─ POST → monday
 └─ on success:
     ComplexityMeter.record(response.data)          (updates samples/total/last_*)
     logger.debug("complexity drain: cost=… budget=…/…")
 └─ return envelope

mondo complexity status
 └─ client.execute("query { me { id } }")           ← injection fires here
 └─ opts.emit(client.meter.to_dict())                ← prints live snapshot
```

---

## 3. Sub-phase history

| Sub-phase | Scope | Commit | +Tests |
|---|---|---|---:|
| **2a** | Board CRUD — `list / get / create / update / archive / delete / duplicate`. Page-based pagination helper `iter_boards_page` (monday's `boards` query is `limit`+`page`, not cursor). `--name-contains` / `--name-matches` applied client-side (no server-side name filter per §16). | `4d9c6f8` | 21 |
| **2b** | Structural column CRUD — `create / rename / change-metadata / delete`. `--defaults` JSON validated then re-serialized (double-JSON §11.4). `ColumnProperty` enum uses `# type: ignore[assignment]` on `title` to avoid shadowing `str.title`. | `b88cbc7` | 10 |
| **2c** | Group CRUD — `list / create / rename / update / reorder / duplicate / archive / delete`. `group_color` validated client-side against monday's 19-hex palette (§10). `reorder` is a clearer UX alias exposing `relative_position_before/_after` via `--after / --before / --position`. | `0e195df` | 22 |
| **2d** | Workspace CRUD — `list / get / create / update / delete / add-user / remove-user / add-team / remove-team`. Reuses `iter_boards_page` with `collection_key="workspaces"`. `WorkspaceKind` is `open|closed` — NOT `private` (common mistake per §14). `update` builds `UpdateWorkspaceAttributesInput` from flags. | `47671ae` | 18 |
| **2e** | Board export — `csv / tsv / json / xlsx / md`. Adds `openpyxl` runtime dep. `iter_items_page` gains `query_initial` / `query_next` kwargs so the subitems-aware variants can be swapped in only when `--include-subitems` is on. xlsx requires `--out`; others default to stdout. Archived columns are dropped. | `b6eb9aa` | 11 |
| **2f** | Bulk import — `import board --from items.csv [--mapping map.yaml]`. Reuses the ColumnCodec registry from item-create. `--idempotency-name` pre-fetches all board names via `iter_items_page` and skips duplicates without a mutation. One result record per row; exit 1 iff any row failed. | `68efb0f` | 10 |
| **2g** | Complexity metering — `MondayClient` auto-rewrites outgoing queries to request `complexity { query before after reset_in_x_seconds }` (brace-matching injector; idempotent). `ComplexityMeter` on each client tracks drain. `--debug` logs each sample. `mondo graphql` opts out via `execute(raw=True)`. New `mondo complexity status` fires a cheap query and prints the live budget. | `f0de815` | 14 |

Total: **7 commits, 106 new tests**, zero regressions.

---

## 4. Key design decisions

### 4.1 Page-based iterator for non-item collections
monday's `boards`, `workspaces`, `users`, `teams` etc. use the older
`limit` + `page` pagination style — not the `items_page` cursor scheme.
Rather than hand-roll a loop in each CLI module, we added a single
`iter_boards_page(query, variables, collection_key, ...)` helper.
`workspace list` just calls it with `collection_key="workspaces"`.

### 4.2 Client-side name filter for boards
The `boards` query takes no `name`-like argument. Phase 1 documented this
as quirk #6. Rather than punt to a JMESPath recipe on the README forever,
2a bakes in `--name-contains` (case-insensitive substring) and
`--name-matches` (regex), applied **after** pagination. Users pay for the
full page scan either way; the CLI just makes it painless.

### 4.3 Reorder as a distinct command
The raw monday API exposes `update_group(attribute: relative_position_after | relative_position_before | position)`.
Exposing this as `group update --attribute relative_position_after --value <group-id>` is accurate but cryptic.
2c adds a `group reorder` command that accepts exactly one of `--after ID`, `--before ID`, or `--position N`
and routes to the right `update_group` attribute under the hood. The raw
`group update` remains available for power users.

### 4.4 Workspace `update` is attribute-object, not enum-scalar
Unlike `update_group` / `update_board` (which take `attribute + new_value`),
`update_workspace` takes a full `UpdateWorkspaceAttributesInput` object.
2d's `workspace update` accepts `--name`, `--description`, `--kind` as
separate optional flags and builds the input dict client-side, requiring
at least one.

### 4.5 `ColumnCodec` registry reused for import
2f would have doubled monday's codec surface if we'd written a parallel
import-time value converter. Instead, `cli/import_.py` calls
`mondo.columns.parse_value(col_type, raw_string, settings)` per cell —
the same function `mondo item create --column K=V` uses. CSV cells like
`Done`, `2026-04-25`, `urgent,blocked` all parse identically to flag
inputs. Tags are still resolved through `create_or_get_tag` at the CLI
layer before hitting the codec (same pattern as item.py).

### 4.6 `--idempotency-name` pre-fetches once, not per-row
The plan §13 sketches a JMESPath-natural-key guard. For Phase 2 we
took the 90%-case simplification: pre-fetch **all** existing item names
on the board before the loop, hold them in a `set[str]`, and skip rows
whose name already exists. This is O(board size) at startup but O(1)
per row — far cheaper than a per-row `items_page` lookup for boards
under ~10k items (monday's hard cap). Full JMESPath guards remain
available for Phase 3 if demand materializes.

### 4.7 XLSX requires `--out`, others default to stdout
Binary formats would corrupt a TTY and aren't useful to pipe. The CLI
returns exit 2 with a clear message if `--format xlsx` is used without
`--out`. For CSV / TSV / JSON / MD the default is stdout — agents that
want to `... | jq` just pipe; humans that want a file pass `--out`.

### 4.8 Export fetches column titles once, items via cursor
For a stable header order, we fetch `boards { columns { id title type } }`
once up front (same `COLUMNS_ON_BOARD` query used by `column list`) and
drop archived columns. Items stream via `iter_items_page`, so a 10k-item
board doesn't materialize in memory twice.

### 4.9 Complexity injection is idempotent and brace-matching
`inject_complexity_field(query)` scans for the outermost matched `{` / `}`
pair and inserts the field before the closing brace. If the query
already mentions `reset_in_x_seconds` (a specific-enough substring),
we leave it alone. Queries without a brace pair (edge case — malformed
input) pass through unchanged.

### 4.10 Complexity injection is opt-out, not opt-in
Defaulting to **on** means every mondo user gets budget telemetry for
free — important for bulk operations like `import board`, where a
runaway script could silently drain the daily call budget. The
`mondo graphql` passthrough opts **out** (`execute(raw=True)`) because
power users sending raw queries expect byte-for-byte fidelity. Tests
that want to assert exact query bytes pass `inject_complexity=False`
to the `MondayClient` constructor.

### 4.11 Meter is per-client, not module-global
Each `MondayClient` instance owns its `ComplexityMeter`. No shared
state means tests don't have to reset globals, and future concurrent
workers (Phase 3 webhook listeners, etc.) can each track independently.
`mondo complexity status` constructs a fresh client, fires one query,
and emits the meter — that's all the state monday gives us anyway
(monday publishes the current budget, not a historical ledger).

---

## 5. Quirks discovered during Phase 2

| # | Discovery | Fix |
|---|---|---|
| 1 | `StrEnum` member named `title = "title"` shadows `str.title()` in mypy strict mode. | `# type: ignore[assignment]` on that single line, documented in a comment. Applies to `ColumnProperty.title` (2b) and `GroupAttribute.title` (2c). |
| 2 | Ruff 0.15.11 `target-version = "py314"` silently rewrites `except (KeyError, TypeError, ValueError):` into Py2-style `except KeyError, TypeError, ValueError:` during auto-format (same bug Phase 1 hit, quirk #3). | Refactored `ComplexityMeter.record` to validate each field individually with `isinstance` guards + a single-type `except ValueError:` — no more multi-type tuple. |
| 3 | Ruff rule `RUF001` rejects the EN DASH `–` that crept into a doc-string as `"1–20 chars"`. | Replaced with ASCII hyphen. Noted for future string-hygiene passes. |
| 4 | `csv.DictReader` silently skips blank lines, so a row `""` under a single-column `name` header produces zero records — not an empty-name row. | Idempotency-test CSV now uses two columns so the blank-name row is still non-blank overall. |
| 5 | `openpyxl` ships no type stubs on PyPI; mypy strict fails on the import. | `# type: ignore[import-untyped]` on the single `from openpyxl import Workbook` line. |
| 6 | `RUF001` flagged our existing string `"1–20 chars"` in `column create` help text after `ruff format` normalized the file; the en-dash had survived Phase 1 undetected. | Fixed; same pattern as #3. |

---

## 6. Exit codes (stable contract — unchanged from Phase 1)

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic error (or import command: at least one row failed) |
| 2 | usage error |
| 3 | auth error |
| 4 | rate / complexity exhausted after retries |
| 5 | validation error (bad column value, unknown column id, ...) |
| 6 | not found (item, board, workspace, group, ...) |
| 7 | network / transport error |

Phase 2 new behaviors that yield non-zero exits:
- `board delete`, `workspace delete`, `group delete` without `--hard` → 2.
- `workspace update` without any of `--name`/`--description`/`--kind` → 2.
- `group create` with a color not in monday's palette → 2.
- `group reorder` without exactly one of `--after`/`--before`/`--position` → 2.
- `export board --format xlsx` without `--out` → 2.
- `import board` with a CSV missing the name column header → 2.
- `import board` where ≥1 row failed (rest still created) → 1.

---

## 7. What's next — Phase 3 preview

Per plan §7 §3, Phase 3 broadens to users/teams, subitems, updates
(comments), workspace docs (distinct from the `doc` column), webhooks,
notifications, tags, file uploads, activity logs, and the aggregation
API. Concrete first targets (matching how Phase 2 sequenced itself):

- **3a** `user list|get|deactivate|activate|update-role|add-to-team|remove-from-team`
- **3b** `team list|create|delete|add-users|remove-users|assign-owners`
- **3c** `subitem create|list|get|move|delete` (separate board IDs, `parent_item` traversal)
- **3d** `update create|list|edit|delete|like|unlike|clear|pin|reply` (item comments)
- **3e** `doc list|create|get|update|delete|add-block|add-content` (workspace-level)
- **3f** `webhook list|create|delete` (with the one-time challenge echo for `create`)
- **3g** `file upload|download` (multipart against `/v2/file`)
- **3h** `activity`, `folder`, `favorite`, `tag`, `notify`, `aggregate`, `validation`

Further ops-readiness items that were flagged by the Phase 2 commits:
- **Ruff bug upstream**: the Py2-style except-tuple rewrite keeps costing
  us time. Quirk #2 above should be escalated to a ruff issue.
- **Integration tests**: Phase 2 has exclusively unit tests against
  pytest-httpx. Nightly integration runs (plan §14, gated on
  `MONDAY_TEST_TOKEN`) would catch schema drift.
- **Live verification**: Phase 1 paired its release with a manual smoke
  run against a real monday account. Phase 2 hasn't had that yet — it
  should precede the v0.2.0 tag.
- **Binary distribution**: still deferred to the v1.0 milestone per §15.

---

## 8. Testing approach

All 525 tests are `pytest` unit tests with `pytest-httpx` mocking the
`/v2` endpoint. Phase 2 added **106 tests** across **7 new test modules**:

```
tests/unit/
├── test_cli_board.py           # 21 cases (2a)
├── test_cli_column.py          # +10 cases (2b, appended)
├── test_cli_group.py           # 22 cases (2c)
├── test_cli_workspace.py       # 18 cases (2d)
├── test_cli_export.py          # 11 cases (2e)
├── test_cli_import.py          # 10 cases (2f)
├── test_complexity.py          # 14 cases (2g)
└── test_client.py              # +1 case adjusted for injection default (2g)
```

Coverage highlights:
- **Pagination**: short-page termination, cursor follow-through,
  max-items truncation, dry-run offline bypass.
- **Enum validation**: case-insensitive inputs (`--kind open`),
  invalid values produce exit 2 without HTTP.
- **Safety guardrails**: confirmation prompts refuse on `n`, `--hard`
  required for deletes, `--yes` bypasses prompts.
- **CSV edge cases**: archived columns filtered, subitems → second
  section/sheet, blank-name row produces failed result, missing
  name-column header exits 2.
- **Complexity**: injector idempotent, mutation + query shapes both
  injected, meter records samples and rejects malformed blocks,
  `raw=True` and `inject_complexity=False` both skip rewriting.

Integration and contract tests remain queued for Phase 3 CI (plan §14,
§16).

---

## 9. Honoring monday API quirks (Phase 2 additions)

Picks up from Phase 1 §11 — additional quirks newly handled:

| Quirk | How Phase 2 handles it |
|---|---|
| `boards` query has **no server-side name filter** | `board list` offers `--name-contains` / `--name-matches` client-side after pagination. |
| `group_color` accepts only the 19 monday palette hex codes | `GROUP_PALETTE` constant; `_validate_color` normalizes (`00c875` → `#00c875`) and rejects non-palette values with exit 2. |
| `DeleteLastGroupException` — deleting the last group on a board fails | Preserved as a server error; CLI surfaces it unchanged. `group delete --hard` is required for any delete. |
| Workspace `kind` is `open|closed`, NOT `private` | `WorkspaceKind` enum uses the correct values; help text calls it out. |
| `update_workspace` takes an attribute **object**, not an enum+scalar | `workspace update` builds `UpdateWorkspaceAttributesInput` from optional `--name`/`--description`/`--kind` flags and requires ≥1 attribute. |
| `column_values` is JSON-stringified (§11.4 double-JSON) | `column create --defaults '<json>'` validates the JSON then re-serializes with `json.dumps` before sending. |
| Status labels / dropdown options can't be updated via `change_column_metadata` — only `title`/`description` | `column change-metadata --property` is a `StrEnum` limited to those two values; anything else is rejected by Typer at arg-parse time. |
| `duplicate_board` / `duplicate_group` are capped at 40/min | Not enforced client-side; rate errors are handled by the existing retry loop. |
| `boards` query uses `limit` + `page`, not cursor | New `iter_boards_page` helper (reused by `workspace list`), stops on short page. |
| monday `complexity` field is the only way to know current budget drain | `MondayClient.execute` auto-injects it (except on `mondo graphql` passthrough); `ComplexityMeter` accumulates; `mondo complexity status` exposes live. |
| `doc` block content is a JSON-encoded string (Phase 1 §5 quirk #5) | Still handled by Phase 1's `docs.py`; Phase 2 added no new doc paths. |

---

## 10. Quick-reference install & run

```bash
# Clone and bootstrap
git clone <repo>
cd mondo
uv sync --all-extras

# Authenticate (any one of these):
export MONDAY_API_TOKEN="eyJhbGci..."     # env (one-off)
uv run mondo auth login                    # OS keyring (recommended)
# or edit ~/.config/mondo/config.yaml (multiple profiles)

# New in Phase 2
uv run mondo board list --name-contains "Pager" -o table
uv run mondo board get --id 1234567890
uv run mondo workspace list --kind open
uv run mondo group list --board 1234567890
uv run mondo column create --board 1234567890 --title Priority --type status \
    --defaults '{"labels":{"1":"High","2":"Medium"}}'
uv run mondo export board --board 1234567890 --format xlsx --out board.xlsx
uv run mondo import board --board 1234567890 --from items.csv --idempotency-name
uv run mondo complexity status

# Verify
uv run pytest                              # 525 green
uv run ruff check src tests
uv run mypy src
```

Phase 2 adds one runtime dependency (`openpyxl>=3.1.5`) and no new dev
dependencies. No breaking changes to Phase 1 commands; all Phase 1
tests continue to pass.

---

*Phase 2 complete. Proposed tag: `v0.2.0`. Total commits on main since
v0.1.0: 7 (2a → 2g). Next: Phase 3 user/team/update/webhook surface.*
