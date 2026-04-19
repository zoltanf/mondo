# monday.com Power-User CLI — Plan, API Reference, and Name Options

Below are the three deliverables. Working tool name `mondo` is used throughout the plan/examples for consistency; the five real name candidates are in Mission 3 at the bottom.

---

## Mission 1 — `plan.md` (this file)

````markdown
# mondo — monday.com Power-User CLI · Implementation Plan

## 1. Scope and positioning

`mondo` is a standalone, az/gh/gam-style command-line client for the monday.com GraphQL API, designed for **both senior admins at a terminal and AI agents in automation pipelines**. It is explicitly **not** a rebrand of monday.com's official `mapps`/`monday-cli`, which only manages monday *apps* — `mondo` is a power-user wrapper for the *platform API* (boards, items, columns, workspaces, users, docs, webhooks, etc.).

**Design pillars**
1. **UX identical to az/gh/gam** — nested command groups, `--output`/`--query`, shell completion, rich tables by default, JSON for scripts.
2. **Single binary per OS/arch** via PyInstaller (same distribution pattern GAM proved at scale).
3. **Dual audience ergonomics** — human-readable tables default; `--output json` and JMESPath `--query` for scripts/agents; `--debug` surfaces every GraphQL query and response.
4. **Safe by default** — token redaction, dry-run for mutating commands, confirmation prompts for destructive operations unless `--yes`.

## 2. Phase roadmap

| Phase | Scope |
|---|---|
| **1 (MVP)** | Item CRUD (create, archive, delete, move, get), column value read/write including the **`doc` column type** (pointer to a workspace doc), `graphql` raw passthrough, auth & config, output formatters, shell completion |
| **2** | Board/column/group/workspace CRUD; data export to CSV/JSON/XLSX/Markdown; bulk import; board templating |
| **3** | Users/teams CRUD, subitems, updates/comments, activity logs, favorites, folders, workspace docs CRUD, webhooks, notifications, tags, file uploads, aggregation API, validation rules, multi-level boards |

## 3. Technology choices

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | user preference, matches GAM distribution model |
| Dependency & project manager | **uv** + `pyproject.toml` (src layout, PEP 621) | user familiarity, 10-100× faster than pip, reproducible `uv.lock` |
| CLI framework | **Typer** (built on Click) | type-hint driven, `app.add_typer()` is the cleanest deep-nesting pattern in Python, first-class shell completion, native Rich integration. Fallback to Click via `typer.main.get_command()` if a plugin needs it. |
| HTTP / GraphQL | **`gql` v3 with `RequestsHTTPTransport`** (sync) | de-facto standard for monday examples, clean `TransportQueryError` surfacing of the `errors` array, freezes cleanly under PyInstaller. Raw `httpx` is an acceptable minimalist alternative. |
| Tables | **Rich** (`rich.table.Table`) | already a Typer transitive, looks great, auto-adapts to terminal width; degrades to plain text when not a TTY |
| Data shaping | **JMESPath** (`jmespath` package, ~100 KB) | az convention, pure Python, no runtime jq dependency |
| YAML | **`ruamel.yaml`** | round-trip preserving; safer than PyYAML for config files |
| Keyring | **`keyring`** (opt-in) | macOS Keychain / Windows Credential Manager / libsecret on Linux (with graceful fallback) |
| Retry/backoff | **`tenacity`** | clean decorators for 429/5xx retry with jitter |
| Packaging | **PyInstaller** (one-folder, tarballed) primary; **Nuitka** as future "speed build" | GAM-proven at scale; one-folder beats one-file on cold-start by ~200 ms |
| Distribution | GitHub Releases tarballs + curl-pipe-bash installer + Homebrew tap (binary formula, not resource formula) + PyPI | broad reach, minimal maintenance |
| Testing | pytest + `pytest-httpx` + `syrupy` (snapshot) + optional integration matrix against a throwaway monday trial account | mock GraphQL without a schema-codegen client |

## 4. Project layout

```
mondo/
├── pyproject.toml
├── uv.lock
├── README.md
├── LICENSE
├── mondo.spec                    # PyInstaller spec
├── Formula/mondo.rb              # Homebrew tap formula (binary)
├── scripts/
│   └── install.sh                # curl|bash installer (GAM-style)
├── .github/workflows/
│   ├── ci.yml                    # lint + test on every PR
│   ├── release.yml               # tag-triggered multi-platform binary build
│   └── pypi.yml                  # trusted publisher PyPI on tags
├── src/mondo/
│   ├── __init__.py
│   ├── __main__.py               # `python -m mondo`
│   ├── version.py                # __version__ = "x.y.z"
│   ├── cli/
│   │   ├── __init__.py           # root Typer app
│   │   ├── main.py               # entry point (console_script)
│   │   ├── globals.py            # --output, --query, --profile, --debug callbacks
│   │   ├── item.py               # `mondo item ...`
│   │   ├── column.py             # `mondo column ...`
│   │   ├── board.py              # phase 2
│   │   ├── group.py              # phase 2
│   │   ├── workspace.py          # phase 2
│   │   ├── user.py               # phase 3
│   │   ├── subitem.py            # phase 3
│   │   ├── update.py             # phase 3
│   │   ├── doc.py                # phase 3
│   │   ├── webhook.py            # phase 3
│   │   ├── export.py             # phase 2 — `mondo export board ...`
│   │   ├── auth.py               # login/logout/status/whoami
│   │   └── graphql.py            # raw passthrough: `mondo graphql 'query { me { id } }'`
│   ├── api/
│   │   ├── client.py             # gql client + retry + complexity metering
│   │   ├── auth.py               # token resolution chain
│   │   ├── errors.py             # exception mapping from monday error codes
│   │   ├── pagination.py         # items_page iterator helpers
│   │   ├── complexity.py         # budget tracking across a session
│   │   └── queries/              # reusable GraphQL snippets as .graphql files
│   │       ├── item_get.graphql
│   │       ├── item_create.graphql
│   │       └── ...
│   ├── columns/
│   │   ├── __init__.py           # registry dispatch
│   │   ├── base.py               # ColumnCodec ABC (parse, encode, render)
│   │   ├── text.py
│   │   ├── status.py
│   │   ├── date.py
│   │   ├── people.py
│   │   ├── ...                   # one module per column type
│   │   └── doc.py                # doc column codec
│   ├── config/
│   │   ├── loader.py             # XDG-compliant config resolution
│   │   └── schema.py             # pydantic v2 models for config.yaml
│   ├── output/
│   │   ├── table.py              # Rich renderer
│   │   ├── json_.py
│   │   ├── yaml_.py
│   │   ├── tsv.py
│   │   ├── csv_.py
│   │   └── query.py              # JMESPath projection
│   ├── logging_.py               # loguru/stdlib logging + SecretStr filter
│   └── util/
│       ├── ids.py                # int/string ID coercion
│       └── kvparse.py            # --column KEY=VALUE parser
└── tests/
    ├── unit/
    ├── snapshot/
    └── integration/              # skipped unless MONDAY_TEST_TOKEN set
```

## 5. CLI UX conventions

### 5.1 Global flags
Exposed on every command via a Typer callback:
- `--profile NAME` / `MONDO_PROFILE` — select profile from config.yaml
- `--api-token TOKEN` / `MONDAY_API_TOKEN` — override token
- `--api-version YYYY-MM` / `MONDAY_API_VERSION` — pin API version (default: `2026-01`, the Current version as of April 2026)
- `--output,-o {table,json,jsonc,yaml,tsv,csv,none}` (default `table` when stdout is a TTY, `json` otherwise — az-style auto-detection)
- `--query,-q <jmespath>` — JMESPath projection applied before rendering
- `--jq <expr>` — courtesy shortcut, shells out to `jq` if present (else errors)
- `--verbose,-v` — info-level logging to stderr
- `--debug` — trace-level logging: logs GraphQL query, variables, response (with token redaction), complexity budget before/after
- `--no-color` / `NO_COLOR` — disable Rich colors
- `--yes,-y` — skip confirmation prompts
- `--dry-run` — print the GraphQL mutation that *would* be sent, don't send

### 5.2 Command grammar
`mondo <group> [<subgroup>] <verb> [--flags]` — az-style. Verbs are consistent: `list`, `get`, `create`, `update`, `delete`, `archive`, `move`, `duplicate`, `export`.

### 5.3 Repeating flags for key=value
`--column K=V` is repeatable. Multiple columns: `--column status=Done --column priority=High`. Values that need structure: `--column dates='{"date":"2026-04-18"}'` or the per-type smart parsers described in §9.

### 5.4 Exit codes
| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic error |
| 2 | usage error (handled by Typer/Click) |
| 3 | auth error (no token, bad token, insufficient scope) |
| 4 | rate/complexity error after retries exhausted |
| 5 | validation error (bad column value, unknown column id) |
| 6 | not found (item, board, workspace, ...) |
| 7 | network / GraphQL transport error |

## 6. Phase 1 command specification

### 6.1 Auth
```
mondo auth login [--profile NAME]
    Interactive: prompt for token, store via keyring (fallback: ~/.config/mondo/credentials.yaml mode 0600).
mondo auth logout [--profile NAME]
mondo auth status
    Prints which token source is active, profile name, scopes, me { id, name, account.slug }.
mondo auth whoami
    Alias for `me` query: prints current user + account.
```

### 6.2 Items
```
mondo item create \
    --board <id> \
    [--group <id>] \
    --name "Item title" \
    [--column <col_id>=<value> ...] \
    [--create-labels-if-missing] \
    [--position-relative-method {before_at,after_at}] \
    [--relative-to <item-id>]

mondo item get --id <id> [--columns col1,col2,...] [--include-updates] [--include-subitems]
mondo item list --board <id> [--group <id>] [--limit N] [--filter '<col>=<val>'] [--order-by <col>]
    Uses items_page + next_items_page with cursor. --limit becomes page size (max 500); paginates until exhausted or --max-items N.
mondo item archive --id <id> [--yes]
mondo item delete  --id <id> [--yes]
mondo item move    --id <id> --group <target-group-id>
mondo item move-to-board --id <id> --board <target-board-id> [--group <id>]
mondo item duplicate --id <id> [--with-updates]
mondo item rename  --id <id> --name "..."
```

Examples:
```
mondo item create --board 1234567890 --group topics --name "Fix CI" \
    --column status=Working --column owner=42 --column date=2026-04-25

mondo item list --board 1234567890 -o json --query "[].{id:id,name:name,status:column_values[?id=='status'].text|[0]}"

mondo item archive --id 9876543210 --yes
```

### 6.3 Columns & column values
```
mondo column list --board <id>
    Prints id, title, type, settings summary as a table.
mondo column get --item <id> --column <col-id> [--raw]
    Default: human-rendered text. --raw: returns {id, type, value (JSON), text}.
mondo column set --item <id> --column <col-id> --value <string-or-json>
    Value is parsed by the registered ColumnCodec for the column's type (see §9).
    Supports --from-stdin and --from-file @path.
mondo column set-many --item <id> --values '{"status":{"label":"Done"},"owner":{"personsAndTeams":[{"id":42,"kind":"person"}]}}'
    Delegates to change_multiple_column_values in a single round-trip.
mondo column clear --item <id> --column <col-id>
    Sends the correct "clear" payload for that column type (empty string, {}, {"clear_all":true} for files, etc.)
```

### 6.4 Doc column (phase 1 — read/write the value of a `doc`-typed column on an item)
```
mondo column doc get --item <id> --column <col-id> [--format markdown|raw-blocks]
    Reads the doc column, extracts object_id, fetches docs(object_ids:[...]) { id object_id blocks { id type content } },
    and either serializes blocks to Markdown (default) or returns raw JSON block array.
mondo column doc set --item <id> --column <col-id> --from-file spec.md
    If column already points to a doc: append markdown via create_doc_block / create_doc_blocks.
    If empty: create_doc(location: { board: { item_id, column_id } }) then import markdown as blocks.
mondo column doc append --item <id> --column <col-id> --markdown "- new bullet"
mondo column doc clear --item <id> --column <col-id>
```
(Full doc CRUD at workspace level is Phase 3: `mondo doc create/list/get/update/delete`.)

### 6.5 Raw GraphQL passthrough
```
mondo graphql '<query or mutation>' [--variables '<json>'] [--file @path]
    Prints { data, errors, extensions } as JSON by default.
    With --output table: best-effort flatten of top-level collection.
mondo graphql --introspect [--version YYYY-MM]
    Fetches SDL from https://api.monday.com/v2/get_schema?format=sdl&version=... and prints it.
```

## 7. Phase 2 & 3 roadmap (sketch)

**Phase 2**
```
mondo board list|get|create|update|archive|delete|duplicate
mondo column create --board <id> --type status --title "Priority" --defaults '{"labels":{"1":"High"}}'
mondo column rename|delete|change-metadata
mondo group create|rename|duplicate|archive|delete|reorder
mondo workspace list|get|create|update|delete|add-user|remove-user
mondo export board <id> --format {csv,json,xlsx,md} [--include-subitems] [--out path]
mondo import board <id> --from items.csv --mapping config.yaml  # bulk item creation with retry
```

**Phase 3**
```
mondo user list|get|deactivate|activate|update-role|add-to-team|remove-from-team
mondo team list|create|delete|add-users|remove-users|assign-owners
mondo subitem create|list|get|move|delete
mondo update create|list|edit|delete|like|unlike|clear|pin|reply
mondo activity board <id> [--since ISO] [--until ISO] [--user N] [--item N]
mondo folder list|create|update|delete|move
mondo favorite list|add|remove
mondo doc list|create|get|update|delete|add-block|add-content
mondo webhook list|create|delete
mondo notify --user <id> --item <id> --text "..."
mondo tag list|create
mondo file upload --item <id> --column <id> --file @path
mondo file download --asset <id> [--out path]
mondo aggregate --board <id> --group-by status --select 'COUNT(*)'
mondo validation list|create|update|delete --board <id>
mondo me
mondo account
```

## 8. GraphQL client architecture

### 8.1 Client (`api/client.py`)
```python
class MondayClient:
    def __init__(self, token: SecretStr, api_version: str = "2026-01",
                 endpoint: str = "https://api.monday.com/v2",
                 timeout: float = 60.0, debug: bool = False):
        transport = RequestsHTTPTransport(
            url=endpoint,
            headers={
                "Authorization": token.reveal(),         # NO "Bearer " prefix — monday is custom
                "API-Version": api_version,
                "Content-Type": "application/json",
                "User-Agent": f"mondo/{__version__}",
            },
            retries=0,   # we handle retry ourselves via tenacity
            timeout=timeout,
        )
        self._gql = GQLClient(transport=transport, fetch_schema_from_transport=False)

    @retry_on_rate_limit
    def execute(self, query: str, variables: dict | None = None,
                include_complexity: bool = True) -> dict:
        if include_complexity:
            query = inject_complexity_field(query)
        result = self._gql.execute(gql(query), variable_values=variables)
        self._record_complexity(result)
        return result
```

### 8.2 Complexity injection
Transform every incoming query to append `complexity { query before after reset_in_x_seconds }` at the top level, and log budget drain at `--debug`. This costs only 0.1 of a daily call (monday rule) and gives us a real-time budget view.

### 8.3 Retry policy (`tenacity`)
```python
@retry(
    retry=retry_if_exception_type((RateLimitError, ComplexityBudgetError, ServerError)),
    wait=wait_exponential_jitter(initial=1, max=60) + wait_from_extensions("retry_in_seconds"),
    stop=stop_after_attempt(5),
    before_sleep=log_before_sleep,
)
```
Error-class mapping (see §8.4): 429 `Rate Limit Exceeded`, `COMPLEXITY_BUDGET_EXHAUSTED`, `IP_RATE_LIMIT_EXCEEDED`, `maxConcurrencyExceeded`, 500–504. Never retry `UserUnauthorizedException`, `ResourceNotFoundException`, `ColumnValueException`, `InvalidArgumentException`.

### 8.4 Error mapping (`api/errors.py`)
```python
ERROR_MAP = {
    "ComplexityException":            ComplexityTooLargeError,      # single-query > 5M
    "COMPLEXITY_BUDGET_EXHAUSTED":    ComplexityBudgetError,        # retryable
    "Rate Limit Exceeded":            RateLimitError,               # retryable
    "maxConcurrencyExceeded":         ConcurrencyError,             # retryable
    "IP_RATE_LIMIT_EXCEEDED":         IPRateLimitError,             # retryable with long backoff
    "UserUnauthorizedException":      AuthError,                    # exit 3
    "USER_UNAUTHORIZED":              AuthError,
    "USER_ACCESS_DENIED":             AuthError,
    "Unauthorized":                   AuthError,
    "ResourceNotFoundException":      NotFoundError,                # exit 6
    "ColumnValueException":           ColumnValueError,             # exit 5
    "CorrectedValueException":        ColumnValueError,
    "InvalidArgumentException":       UsageError,
    "InvalidColumnIdException":       UsageError,
    "InvalidUserIdException":         UsageError,
    "InvalidBoardIdException":        UsageError,
    "InvalidVersionException":        UsageError,
    "ItemNameTooLongException":       ValidationError,
    "ItemsLimitationException":       ValidationError,              # >10,000 items/board
    "RecordInvalidException":         ValidationError,              # 422
    "missingRequiredPermissions":     AuthError,
    "DeleteLastGroupException":       UsageError,
    "JsonParseException":             UsageError,
    "API_TEMPORARILY_BLOCKED":        ServiceError,                 # retryable
    "Resource is currently locked":   ServiceError,                 # retryable
}
```
Every GraphQL error surfaces `request_id` from `extensions` in the user-facing message — monday's recommended troubleshooting handle (introduced May 19 2025).

### 8.5 Pagination iterator (`api/pagination.py`)
```python
def iter_items_page(client, board_id, limit=500, query_params=None, max_items=None):
    first = client.execute(INITIAL_ITEMS_PAGE, {
        "boardIds": [board_id], "limit": limit, "queryParams": query_params})
    page = first["data"]["boards"][0]["items_page"]
    yielded = 0
    for it in page["items"]:
        if max_items and yielded >= max_items: return
        yield it; yielded += 1
    cursor = page["cursor"]
    while cursor:
        nxt = client.execute(NEXT_ITEMS_PAGE, {"cursor": cursor, "limit": limit})
        page = nxt["data"]["next_items_page"]
        for it in page["items"]:
            if max_items and yielded >= max_items: return
            yield it; yielded += 1
        cursor = page["cursor"]
```
Handles `CursorExpiredError` by re-issuing the initial page (cursor lifetime is 60 minutes per monday docs).

### 8.6 Rate-limit awareness
- Honor `Retry-After` HTTP header on 429.
- Honor `extensions.retry_in_seconds` from `COMPLEXITY_BUDGET_EXHAUSTED`.
- Maintain an in-process *complexity-budget meter* across a session so batch operations can self-throttle before hitting the wall.
- Concurrency limit defaults to 5 worker threads for bulk ops (below the Core/Pro/Enterprise floor of 40/100/250) — configurable via `MONDO_CONCURRENCY`.

## 9. Column value handling — smart codecs

The hardest part of the monday API (see `monday-api.md` §Columns) is that every column type has its own JSON shape for writes. `mondo` exposes a **ColumnCodec** plugin per type:

```python
class ColumnCodec(ABC):
    type_name: ClassVar[str]
    @abstractmethod
    def parse(self, user_input: str, settings: dict) -> dict:
        """Turn user-supplied shorthand into the monday JSON write shape."""
    @abstractmethod
    def render(self, value: dict | None, text: str | None) -> str:
        """Turn the read {value,text} into a human-readable string."""
```

**Shorthand conventions** (so users rarely type raw JSON):
| Column type | `--column <id>=<shorthand>` | Expands to |
|---|---|---|
| text | `notes="hello"` | `"hello"` (simple string) |
| long_text | `notes="multi\nline"` | `{"text":"multi\nline"}` |
| numbers | `price=42.5` | `"42.5"` |
| status | `status=Done` or `status=#1` | `{"label":"Done"}` / `{"index":1}` |
| date | `due=2026-04-25` or `due=2026-04-25T10:00` | `{"date":"2026-04-25"}` / `{"date":"...","time":"10:00:00"}` |
| timeline | `range=2026-04-01..2026-04-15` | `{"from":"...","to":"..."}` |
| week | `wk=2026-W16` | `{"week":{"startDate":"2026-04-13","endDate":"2026-04-19"}}` |
| hour | `remind=14:30` | `{"hour":14,"minute":30}` |
| people | `owner=42` or `owner=42,51,team:7` | `{"personsAndTeams":[{"id":42,"kind":"person"},...]}` |
| dropdown | `cats=Cookie,Cupcake` or `cats=id:1,2` | labels or ids |
| email | `email=a@b.com` or `email=a@b.com,"Display"` | `{"email":"...","text":"..."}` |
| phone | `phone=+19175998722,US` | `{"phone":"...","countryShortName":"US"}` |
| link | `link=https://x.com,"click me"` | `{"url":"...","text":"..."}` |
| location | `loc=40.68,-74.04,"NYC"` | `{"lat":"...","lng":"...","address":"..."}` |
| country | `country=US` | `{"countryCode":"US","countryName":"United States"}` |
| checkbox | `done=true` / `done=false` / `done=clear` | `{"checked":"true"}` / `null` / `null` |
| rating | `stars=4` | `{"rating":4}` |
| tags | `tags=295026,295064` or `tags=urgent,blocked` | `{"tag_ids":[...]}` (auto-calls `create_or_get_tag` if names given) |
| board_relation | `rel=12345,23456` | `{"item_ids":[12345,23456]}` |
| dependency | `deps=12345,23456` | `{"item_ids":[12345,23456]}` |
| doc | `spec=@path/to/file.md` | creates/overwrites doc (see §6.4) |
| file | `file=@path` | routes to `add_file_to_column` on `/v2/file` endpoint |

Users can always bypass shorthand with raw JSON: `--column status='{"index":3}'` (single-quote to avoid shell escaping). Force raw mode with `--column-raw status='{"index":3}'`.

## 10. Configuration

```yaml
# ~/.config/mondo/config.yaml  (XDG: $XDG_CONFIG_HOME/mondo/config.yaml)
default_profile: personal
api_version: "2026-01"

profiles:
  personal:
    api_url: https://api.monday.com/v2
    api_token: ${MONDAY_API_TOKEN}          # shell env expansion
    default_board_id: 1234567890
    output: table

  marktguru:
    api_url: https://api.monday.com/v2
    api_token_keyring: mondo:marktguru      # resolved via `keyring.get_password("mondo","marktguru")`
    default_workspace_id: 42
    api_version: "2026-01"                  # profile can override global

  sandbox:
    api_url: https://api.monday.com/v2
    api_token: MY_THROWAWAY_TOKEN           # discouraged — warn on load
    api_version: "2026-04"                  # test the RC
```

**Token resolution precedence:** `--api-token` flag → `MONDAY_API_TOKEN` env → profile's `api_token_keyring` → profile's `api_token` → fail with helpful message pointing to `mondo auth login`.

**Credential file** `~/.config/mondo/credentials.yaml` mode 0600 is the keyring fallback on headless Linux. Never written by default — only when `keyring.set_password` raises.

## 11. Output formatting

### Formatter registry
```python
FORMATTERS = {
  "table": TableFormatter,       # Rich, TTY default
  "json":  JsonFormatter,        # compact, machine default
  "jsonc": JsonColoredFormatter, # rich-highlighted for humans
  "yaml":  YamlFormatter,
  "tsv":   TsvFormatter,
  "csv":   CsvFormatter,
  "none":  NoopFormatter,        # only useful with --query for a single value
}
```

### Table rules
- Top-level array → one row per element, columns = union of top-level scalar keys (az default behavior).
- Top-level object → two-column key/value.
- Nested structures → collapse to `<…>`; users wanting deep data should use `-o json --query …`.

### JMESPath projection
Applied *before* formatting. `mondo item list --board X -q "[].name"` returns bare names. Agents should prefer `-o json -q "[].{id:id,name:name}"` for a stable shape they can parse.

## 12. Logging, debug, dry-run

- Default: WARNING+ to stderr, nothing on stdout except the formatter output.
- `-v`: INFO to stderr (request URLs, complexity drain, retry events).
- `--debug`: full GraphQL query + variables + response to stderr as pretty-printed JSON, with SecretStr-redacted headers. Also enables `httpx`/`gql` wire log.
- `--dry-run`: on any mutating command, print the exact GraphQL mutation and variables that *would* be sent, then exit 0 without calling the API.
- `MONDO_LOG_FILE=/path/to/mondo.log`: optional rotating file sink (10 MB × 3).

**Token redaction:** a logging filter regex-replaces any occurrence of the raw token or bearer-like 20+ char token pattern with `***`. `SecretStr` class `__repr__` returns `"***"`. `pretty_exceptions_show_locals=False` in production builds.

## 13. Idempotency

The monday API **does not support idempotency keys** (confirmed — no `Idempotency-Key` header documented). Mondo compensates:
- Mutating commands that *could* be retried (create, duplicate) support `--idempotency-guard '<natural-key-jmespath>'` — before mutating, `mondo` queries for an existing item matching the natural key (e.g., `name` + `board_id` + specific column value) and skips if found. This is client-side only and best-effort.
- Destructive commands (`delete`, `archive`, `move`) prompt for confirmation unless `--yes` is set.
- `mondo item archive` is inherently reversible (30-day recovery window per monday), so it's the default; `delete` requires `--yes` and `--hard` for clarity.

## 14. Testing strategy

### Unit tests
- Mock the `/v2` endpoint with `pytest-httpx`. Each column codec has round-trip tests: parse → expected JSON, render → expected display text.
- Snapshot tests (`syrupy`) on help output to catch accidental flag changes.
- Error-map tests: inject synthetic GraphQL error responses and assert the right exception class + exit code.

### Integration tests
- Gated on `MONDAY_TEST_TOKEN` and `MONDAY_TEST_BOARD_ID` env vars (a throwaway Free-tier trial board).
- Matrix: each Phase 1 command × each output format × `--api-version {maintenance, current, rc}`.
- Guarded with `@pytest.mark.integration` and skipped in PR CI; run nightly on `main`.

### Contract tests
- Fetch SDL for each supported API version and assert the subset of types/fields `mondo` depends on still exists. Fail loudly when a field `mondo` uses is deprecated.

## 15. Distribution

### Primary — PyInstaller one-folder tarballs per OS/arch
Build matrix (GitHub-hosted runners):

| Runner | Arch | Target triple |
|---|---|---|
| `macos-14` | arm64 | `darwin-arm64` |
| `macos-13` | x86_64 | `darwin-amd64` |
| `ubuntu-latest` | x86_64 | `linux-amd64` (built inside `manylinux_2_28` container for wide glibc support) |
| `ubuntu-24.04-arm` | arm64 | `linux-arm64` |
| `windows-latest` | x86_64 | `windows-amd64` (optional) |

Each job:
1. `uv sync --frozen`
2. `pyinstaller --clean --noconfirm mondo.spec` (one-folder mode)
3. macOS: `codesign -o runtime --timestamp -s "Developer ID Application: marktguru"` → zip → `xcrun notarytool submit --wait`
4. `tar -cJf mondo-<ver>-<target>.tar.xz mondo/`
5. `shasum -a 256` sidecar + `actions/attest-build-provenance` SLSA attestation
6. Upload to GitHub Release

### Secondary — Homebrew tap (binary formula)
`marktguru/homebrew-tap` with a `mondo.rb` formula that downloads the per-platform tarball from GitHub Releases (not a resource-based Python formula — avoids the azure-cli venv maintenance trap):
```ruby
class Mondo < Formula
  desc "Power-user CLI for monday.com"
  homepage "https://github.com/marktguru/mondo"
  version "1.0.0"; license "MIT"
  on_macos do
    on_arm   do; url ".../mondo-1.0.0-darwin-arm64.tar.xz";  sha256 "..." end
    on_intel do; url ".../mondo-1.0.0-darwin-amd64.tar.xz"; sha256 "..." end
  end
  on_linux do
    on_arm   do; url ".../mondo-1.0.0-linux-arm64.tar.xz";  sha256 "..." end
    on_intel do; url ".../mondo-1.0.0-linux-amd64.tar.xz"; sha256 "..." end
  end
  def install
    libexec.install Dir["*"]
    bin.install_symlink libexec/"mondo"
    generate_completions_from_executable(bin/"mondo", "--show-completion")
  end
  test do; assert_match "mondo", shell_output("#{bin}/mondo --version"); end
end
```
Command: `brew install marktguru/tap/mondo`.

### Tertiary — curl-pipe-bash installer (GAM-style)
`scripts/install.sh` hosted at a stable URL: detects OS/arch, downloads the right tarball + checksum from GitHub Releases, verifies sha256, extracts to `~/.local/share/mondo/`, symlinks `~/.local/bin/mondo`. One-liner: `curl -fsSL https://mondo.sh/install | bash`.

### Quaternary — PyPI (`pip install mondo`)
For Python users who want it. Same source, no frozen binary. Trusted-publisher workflow; no API tokens in CI.

### Linux packages (future)
deb/rpm via `nfpm` from the same tarballs; Arch AUR PKGBUILD; optional Snap if demand materializes.

## 16. CI/CD outline

```
.github/workflows/
  ci.yml       on: [pull_request, push to main]
               jobs: lint (ruff), type-check (mypy), unit tests (3.11/3.12/3.13 × macOS/Linux/Windows)
  release.yml  on: [push tags v*]
               jobs: build matrix above, gh-release, Homebrew-tap-bump PR
  pypi.yml     on: [push tags v*]
               job: sdist + wheel + trusted-publisher upload
  contract.yml on: [schedule nightly]
               job: introspect current/rc API versions, fail if breakage
```

## 17. Security checklist

- Token never printed by default; `SecretStr` wrapping; log filter regex.
- HTTPS only; explicit TLS verification.
- Minimal dep surface (`uv sync --no-dev` for frozen builds).
- SBOM generated per release (`syft`), uploaded to the Release.
- SLSA level 3 build provenance via `actions/attest-build-provenance`.
- `mondo auth login` warns if terminal is not a TTY (prevents token in shell history).
- Rate-limit self-throttling to prevent accidentally nuking an account's daily call budget.

## 18. Open questions for implementer

1. Which Python version to target as PyInstaller floor — 3.11 (supports through Oct 2027) is recommended; 3.13 for Nuitka-preview builds.
2. Whether to embed a vendored MCP server mode (`mondo mcp serve`) so the binary doubles as an MCP provider for agents — logical Phase 3 bonus given monday already ships one (https://monday.com/w/mcp).
3. File-upload streaming: stream from stdin when `--file -` to support large uploads without temp files.
4. Cache schema introspection (`/v2/get_schema?version=...`) in `~/.cache/mondo/` and use it for client-side arg validation.
````

---

## Mission 2 — `monday-api.md`

````markdown
# monday.com GraphQL API — Implementation Reference

Source: https://developer.monday.com/api-reference/ (retrieved April 2026). This document is the primary reference for implementing `mondo`. Every section is opinionated toward implementation correctness, not marketing accuracy.

---

## 1. Transport basics

- **Endpoint:** `https://api.monday.com/v2` — HTTP POST only, JSON body `{"query": "...", "variables": {...}}`.
- **File-upload endpoint:** `https://api.monday.com/v2/file` — multipart/form-data only. The regular `/v2` endpoint does not accept `File` variables.
- **Schema introspection:** `GET https://api.monday.com/v2/get_schema` (JSON) or `?format=sdl` (SDL). Pin a version with `?version=YYYY-MM`.

### Required headers
```
Authorization: <TOKEN>          # monday uses the token directly — NO "Bearer " prefix
Content-Type:  application/json
API-Version:   2026-01          # strongly recommended, see §3
User-Agent:    mondo/x.y.z      # good practice, not required
```

**Token format caveat:** third-party blogs often show `Authorization: Bearer <token>`. The official docs do **not** use `Bearer`. Pass the token as-is.

### Response envelope
```json
{
  "data":    { ... },                 // may be partial when errors are present
  "errors":  [ { "message": "...", "path": [...], "locations": [...],
                 "extensions": { "code": "...", "status_code": 200 } } ],
  "account_id": 12345,                // removed from default responses in 2025-04 — query `account` instead
  "extensions": { "request_id": "uuid-here" }   // since May 19 2025 — include in bug reports
}
```

---

## 2. Authentication

- **Personal API token (V2)** — per-user, copy from Profile → Developers → API Token → Show (admins: Administration → Connections → Personal API token). Regenerating instantly invalidates the old one. Scope = that user's UI permissions.
- **OAuth access token** — for apps, via the OAuth 2.0 flow at `https://auth.monday.com/oauth2/authorize` → `https://auth.monday.com/oauth2/token`. Valid until app uninstall. Honors declared OAuth scopes.
- **shortLivedToken** — embedded in the JWT monday sends to apps on user interaction. Valid 5 minutes; useful for "act on behalf of current user" inside apps.
- **Global / service tokens** exist for internal monday use only; not user-accessible.

**Scopes** (OAuth apps): `me:read`, `boards:read`, `boards:write`, `workspaces:read`, `workspaces:write`, `users:read`, `users:write`, `account:read`, `notifications:write`, `updates:read`, `updates:write`, `assets:read`, `tags:read`, `webhooks:read`, `webhooks:write`, `docs:read`, `docs:write`. For personal tokens, scopes are implicit in the user's UI rights.

**Errors to catch:**
- `Unauthorized` / HTTP 401 — missing or malformed token
- `UserUnauthorizedException` / `USER_UNAUTHORIZED` / `USER_ACCESS_DENIED` (HTTP 403) — token lacks scope/permission. (Renamed 2025-07.)
- `missingRequiredPermissions` — OAuth app missing a scope.

---

## 3. API versioning

monday guarantees ≥3 parallel versions and releases quarterly. Each version goes **RC → Current (3 mo) → Maintenance (3 mo) → Deprecated (announced ≥6 mo in advance)**.

### Lifecycle as of April 2026
| Version | Status |
|---|---|
| **2024-10** | Deprecated Feb 15 2026 — requests fall through to 2025-04 |
| **2025-01** | Deprecated Feb 15 2026 — requests fall through to 2025-04 |
| **2025-04** | Maintenance (deprecated Q3 2026 tentative) |
| **2025-07** | Maintenance |
| **2025-10** | Maintenance |
| **2026-01** | **Current** (default when header omitted) — recommended for `mondo` v1.0 |
| **2026-04** | Release Candidate |

Invalid `API-Version: 2023` → `InvalidVersionException`. Nonexistent version → falls back to Current silently.

```graphql
query { version { kind value } versions { value kind } }  # introspect active/known versions
```

**Breaking changes in 2025-04 (still relevant):**
- Unified error format (GraphQL-spec compliant: `extensions.code`)
- Stricter parser (line breaks in strings, nulls in non-nullable fields now rejected)
- `account_id` removed from default response envelope — query `account { id }` instead
- `updates` max page size reduced to 100
- Server-side column validation enforcement

**2026-01 additions:**
- `aggregate` root query (see §14)
- `doc_version_history`, `doc_version_diff`
- `notetaker.meetings`
- `object_relations` CRUD (ALIAS / DEPENDENCY relations)
- `articles` (knowledge base) API
- `enroll_items_to_sequence` mutation
- `ask_developer_docs` AI query

**2026-04 RC:**
- Multi-level boards enabled by default (up to 5 subitem levels + rollups)

---

## 4. Rate limits

Six distinct limits — all enforced **per account, per app** (personal tokens count as one "app"). Failed calls still consume budget.

| Limit | Value |
|---|---|
| **Single-query complexity** | **5,000,000 points max** per query |
| Complexity/min, app tokens | 5M reads + 5M writes, tracked separately |
| Complexity/min, playground | same as app tokens (1M combined on Trial/Free) |
| Complexity/min, personal tokens | 10M combined (1M on Trial/NGO/Free) |
| **Daily call limit** | Free/Trial: 200 · Standard/Basic: 1,000 · Pro: 10,000 (soft) · Enterprise: 25,000 (soft) · resets midnight UTC |
| **Requests/min** | Enterprise: 5,000 · Pro: 2,500 · Other: 1,000 |
| **Concurrency** | Enterprise: 250 · Pro: 100 · Other: 40 |
| **IP-based** | 5,000 requests / 10 seconds / IP |

**Per-minute budgets use a sliding window** starting at the first call.

**Endpoint-specific caps:**
- `create_board`, `duplicate_board`, `duplicate_group`: 40/min each
- `connect_project_to_portfolio`: 15/min
- Root `items(ids: [...])` query with >100 IDs, or with no filters at all: **1 call / 2 minutes** (these share the budget)
- `app_subscriptions`: 120/min
- `FormulaValue.display_value`: 10,000 formula values/min, max 5 formula columns per request

**Daily-call accounting:**
- Rate-limit-error responses count as **0.1 calls**
- Isolated `complexity` queries count as **0.1 calls** (free budget checks)
- High-complexity queries may count as **>1 call**

### Rate-limit error shapes
```json
// Minute limit
{"errors":[{"message":"Rate Limit Exceeded",
  "extensions":{"code":"RATE_LIMIT_EXCEEDED","retry_in_seconds":60,"status_code":429}}]}

// Concurrency
{"errors":[{"message":"Max concurrent requests exceeded",
  "extensions":{"code":"maxConcurrencyExceeded","status_code":429}}]}

// IP
{"errors":[{"message":"IP rate limit exceeded",
  "extensions":{"code":"IP_RATE_LIMIT_EXCEEDED","status_code":429}}]}

// Complexity budget (simplified since 2025-07)
{"errors":[{"message":"Complexity budget exhausted",
  "extensions":{"code":"COMPLEXITY_BUDGET_EXHAUSTED","retry_in_seconds":60}}]}
```
Honor the `Retry-After` HTTP header or `extensions.retry_in_seconds` field — whichever is present. Use capped exponential backoff with jitter otherwise.

---

## 5. Complexity

Every query has a **complexity cost**. Include this field on every request to monitor budget live:
```graphql
query { complexity { query before after reset_in_x_seconds } ...rest }
```
- `query`: cost of this call
- `before`/`after`: budget before/after this call
- `reset_in_x_seconds`: seconds until the sliding window resets

### Calculation
- Each field has a base cost
- `limit` multiplies: `complexity(field) = field_base × limit`
- Nesting multiplies: `boards(limit:10) { items_page(limit:100) { column_values { ... } } }` ≈ 10 × 100 × base
- Fragments reuse cost — repeated nested lookups are expensive

### Single-query ceiling: 5,000,000 points
A fat `create_item` is already ~30,000 points. A query pulling 500 items × 50 column_values from 10 boards can exceed 5M.

### Reduction tactics (from monday docs)
1. Request only needed fields — specifically list `columns(ids: [...])` instead of all
2. Use `limit` / `page` / cursor pagination
3. Split nested pulls into separate roundtrips (initial `items_page` returns IDs only → `items(ids:)` batches of 100 for details)
4. Use `change_multiple_column_values` (single mutation) instead of N × `change_column_value`
5. Reuse fragments — GraphQL fragment reuse is free, copy/paste isn't

---

## 6. Error handling

**Response style (since 2025-01, GraphQL-spec compliant):** application errors return HTTP 200 with an `errors` array; transport errors return 4xx/5xx. Partial data is supported — `data` and `errors` can coexist, failed fields are `null`.

### Error object shape
```json
{"message": "...", "path": ["boards", 0, "items_page"],
 "locations": [{"line": 2, "column": 3}],
 "extensions": {"code": "ColumnValueException",
                "status_code": 200,
                "error_data": { ... },
                "request_id": "abc-123" }}
```

### Full error code catalog
**Application (HTTP 200)**: `ColumnValueException`, `CorrectedValueException`, `CreateBoardException`, `InvalidArgumentException`, `InvalidBoardIdException`, `InvalidColumnIdException`, `InvalidUserIdException`, `InvalidVersionException`, `ItemNameTooLongException`, `ItemsLimitationException` (>10,000 items/board), `missingRequiredPermissions`, `ParseError on...`, `ResourceNotFoundException`, `API_TEMPORARILY_BLOCKED`, `CursorException`/`CursorExpiredError`.

**4xx**: `400 Bad Request`, `400 JsonParseException`, `401 Unauthorized`, `401 Your IP is restricted`, `403 UserUnauthorizedException`/`USER_UNAUTHORIZED`, `403 USER_ACCESS_DENIED`, `404 ResourceNotFoundException`, `409 DeleteLastGroupException`, `422 RecordInvalidException` (>400 board subscribers, >10,000 subscriptions), `423 Resource is currently locked`, `429 maxConcurrencyExceeded`, `429 Rate Limit Exceeded`, `429 COMPLEXITY_BUDGET_EXHAUSTED`, `429 IP_RATE_LIMIT_EXCEEDED`.

**5xx**: `500 Internal Server Error` — usually malformed JSON column value or bad ID; retry after delay.

### Retry policy recommendation
| Error | Retry? | Strategy |
|---|---|---|
| 429 Rate Limit / Complexity Budget | yes | honor `retry_in_seconds`, capped exp backoff |
| 429 Concurrency | yes | jittered short backoff (50–500 ms) |
| 429 IP | yes | long backoff (5–30 s) |
| 423 Locked / 503 / 504 / 500 | yes | exp backoff, 3 tries max |
| `API_TEMPORARILY_BLOCKED` | yes | exp backoff |
| `Resource is currently locked` | yes | short backoff |
| 400 / 401 / 403 / 404 | no | surface to user |
| `ColumnValueException`, `InvalidArgument*` | no | surface |
| Cursor expired | no (but re-issue initial page) | refresh |

Always include `request_id` in user-facing errors.

---

## 7. Pagination

Monday deprecated offset-based pagination on items; use cursor-based `items_page` + `next_items_page`.

### First page (nested inside `boards`)
```graphql
query ($boardIds: [ID!]!, $limit: Int!, $queryParams: ItemsQuery) {
  complexity { query before after reset_in_x_seconds }
  boards(ids: $boardIds) {
    items_page(limit: $limit, query_params: $queryParams) {
      cursor
      items { id name group { id title } column_values { id type text value } }
    }
  }
}
```

### Continuation (root level — cheaper, no board re-resolution)
```graphql
query ($cursor: String!, $limit: Int!) {
  next_items_page(cursor: $cursor, limit: $limit) {
    cursor
    items { id name }
  }
}
```

- **Max limit per page: 500**
- **Cursor lifetime: 60 minutes** — expired cursor → `CursorExpiredError`. Restart from initial page.
- `cursor: null` on last page → iteration complete.
- `query_params` accepts:
  - `rules`: `[{ column_id: "status", compare_value: ["Done"], compare_attribute: "", operator: any_of }]`
  - `operator`: `and | or` between rules
  - `order_by`: `[{ column_id: "date4", direction: asc }]`
  - `ids`: max **100** item IDs (even though `limit` can be 500) — use for keyset lookups
- **Cannot filter on `mirror` or `formula` columns** — throws `InvalidColumnTypeException`.

### Pattern for very large boards
```
1. items_page(limit:500, query_params:{...}) → collect IDs + cursor
2. next_items_page(cursor) loop until cursor:null (IDs only)
3. items(ids:[...100...]) in parallel (respecting concurrency limit) to fetch column_values
```

---

## 8. Boards

**Query:**
```graphql
boards(ids: [ID!], limit: Int = 25, page: Int = 1,
       board_kind: BoardKind, state: State = active,
       workspace_ids: [ID], order_by: BoardsOrderBy,
       ids_as_numbers: Boolean): [Board]
```
`BoardKind`: `public | private | share`.
`State`: `active | archived | deleted | all`.
`BoardsOrderBy`: `used_at | created_at`.

**Board type — key fields:**
```
id, name, description, state, board_kind, board_folder_id, workspace_id,
items_count, columns, groups, owners, subscribers, tags, top_group,
views, permissions, hierarchy_type (classic | multi_level),
activity_logs(...), items_page(limit, cursor, query_params)
```

**Mutations:**
- `create_board(board_name: String!, board_kind: BoardKind!, description, folder_id, workspace_id, template_id, board_owner_ids, board_owner_team_ids, board_subscriber_ids, board_subscriber_teams_ids, empty)` → `Board`. Cannot create multi-level boards.
- `duplicate_board(board_id: ID!, duplicate_type: DuplicateBoardType!, board_name, workspace_id, folder_id, keep_subscribers)` → `BoardDuplication`. **Async** — response may be partial.
  - `DuplicateBoardType`: `duplicate_board_with_structure | duplicate_board_with_pulses | duplicate_board_with_pulses_and_updates`.
- `update_board(board_id: ID!, board_attribute: BoardAttributes!, new_value: String!)` — attrs: `name | description | communication | item_nickname` (2026-04).
- `archive_board(board_id: ID!)` → `Board`
- `delete_board(board_id: ID!)` → `Board`
- `add_subscribers_to_board(board_id, user_ids, kind: BoardSubscriberKind)`, `add_teams_to_board`, `delete_subscribers_from_board`, `delete_teams_from_board`.

**Gotchas:**
- `create_board`, `duplicate_board` capped at 40/min each.
- Until API 2026-04 the `boards` query excludes multi-level boards by default.
- Many ID args migrated from `Int` → `ID` (string-coerced) — pin version for consistency.

---

## 9. Items

**Query:**
```graphql
items(ids: [ID!], limit: Int = 25, page: Int = 1,
      newest_first: Boolean, exclude_nonactive: Boolean): [Item]
```
`Item` key fields: `id, name, state, created_at, updated_at, creator_id, creator, group { id title }, board { id name }, parent_item, subitems, column_values(ids, types) { id type text value column { ... } }, updates(limit, page), assets`.

**Mutations (all return `Item`):**
- `create_item(board_id: ID!, item_name: String!, group_id: String, column_values: JSON, create_labels_if_missing: Boolean, position_relative_method: PositionRelative, relative_to: ID)` — `PositionRelative`: `before_at | after_at`. ~30k complexity.
- `duplicate_item(board_id: ID!, item_id: ID!, with_updates: Boolean)`
- `archive_item(item_id: ID!)`
- `delete_item(item_id: ID!)`
- `move_item_to_group(item_id: ID!, group_id: String!)`
- `move_item_to_board(item_id: ID!, board_id: ID!, group_id, columns_mapping: [ColumnMappingInput!], subitems_columns_mapping: [ColumnMappingInput!])` — mapping tells monday how to translate source column IDs to dest column IDs.
- `change_item_name(board_id: ID!, item_id: ID!, new_name: String!)`
- `set_item_description_content(item_id: ID!, markdown: String!)` → `{ success, error, block_ids }` (2026-04)

**Gotchas:**
- Root `items` without IDs, or with >100 IDs, is rate-limited to **1 call / 2 minutes**.
- `column_values` is a `JSON!` scalar — pass as a **JSON-stringified string** (see §11).
- On multi-level boards, mutations that touch calculated rollups silently no-op.

### Example
```graphql
mutation ($boardId: ID!, $name: String!, $vals: JSON!) {
  create_item(board_id: $boardId, item_name: $name,
              column_values: $vals, create_labels_if_missing: true) {
    id name
  }
}
# variables:
# { "boardId": 1234567890, "name": "Task",
#   "vals": "{\"status\":{\"label\":\"Done\"},\"due\":{\"date\":\"2026-04-25\"}}" }
```

---

## 10. Groups

No root `groups` query — always nested: `boards { groups(ids: [String]) { id title color position archived deleted items_page(...) } }`. **Group IDs are strings** (`"topics"`, `"new_group_8A3F"`).

**Mutations:**
- `create_group(board_id: ID!, group_name: String!, group_color: String, relative_to: String, position_relative_method: PositionRelative, position: String)` → `Group`
- `update_group(board_id: ID!, group_id: String!, group_attribute: GroupAttributes!, new_value: String!)` — attrs: `title | color | position | relative_position_after | relative_position_before`
- `duplicate_group(board_id: ID!, group_id: String!, add_to_top: Boolean, group_title: String)` → `Group` — 40/min cap; does NOT duplicate item updates
- `archive_group(board_id: ID!, group_id: String!)` → `Group`
- `delete_group(board_id: ID!, group_id: String!)` → `Group` — cascades to items; cannot delete last group (`DeleteLastGroupException`)

`group_color` accepts the monday palette hex codes only (`#037f4c`, `#00c875`, `#9cd326`, `#cab641`, `#ffcb00`, `#784bd1`, `#9d50dd`, `#007eb5`, `#579bfc`, `#66ccff`, `#bb3354`, `#df2f4a`, `#ff007f`, `#ff5ac4`, `#ff642e`, `#fdab3d`, `#7f5347`, `#c4c4c4`, `#757575`).

---

## 11. Columns & column values v2 — **the hardest part**

### 11.1 Column queries
```graphql
boards(ids: [ID!]) {
  columns(ids: [String!], types: [ColumnType!]) {
    id title type description settings_str archived width
  }
}
```
`settings_str` is a JSON-encoded string describing column-specific settings (status labels, dropdown options, rating scale, etc.). **Parse it to get status index ↔ label mapping.**

### 11.2 Column mutations
- `create_column(board_id: ID!, title: String!, column_type: ColumnType!, description, defaults: JSON, id: String, after_column_id: ID)` → `Column`. Custom `id` must be 1–20 chars, lowercase alphanumeric + underscores, unique per board.
- `change_column_title(board_id: ID!, column_id: String!, title: String!)`
- `change_column_metadata(board_id: ID!, column_id: String!, column_property: ColumnProperty!, value: String!)` — only `title` and `description` are settable; to add status labels use `create_labels_if_missing: true` when writing values.
- `delete_column(board_id: ID!, column_id: String!)`

### 11.3 Value-writing mutations
| Mutation | When to use |
|---|---|
| `change_simple_column_value(item_id: ID, board_id: ID!, column_id: String!, value: String, create_labels_if_missing: Boolean)` | quickest for text/numbers/status-by-label — accepts plain strings |
| `change_column_value(item_id: ID, board_id: ID!, column_id: String!, value: JSON!, create_labels_if_missing: Boolean)` | single column, full JSON — most flexible for any type |
| `change_multiple_column_values(item_id: ID, board_id: ID!, column_values: JSON!, create_labels_if_missing: Boolean)` | **preferred** when setting ≥2 columns — single mutation, 1 complexity budget hit |
| `create_column_value` | for creating a value on a new item when using `create_item`, same JSON shape as `column_values` |

All three return `Item`.

### 11.4 The double-JSON gotcha
The `value` / `column_values` argument is GraphQL scalar type `JSON!`, but monday's implementation **expects a JSON-encoded string** (not a literal JSON object). So you must call `json.dumps(obj)` *even though the argument type is JSON*. Two practical patterns:

**Inline (painful — double-escaping):**
```graphql
mutation { change_column_value(item_id: 1, board_id: 2, column_id: "status",
  value: "{\"label\":\"Done\"}") { id } }
```

**Variable (recommended):**
```graphql
mutation ($value: JSON!) {
  change_column_value(item_id: 1, board_id: 2, column_id: "status", value: $value) { id }
}
# variables JSON
{ "value": "{\"label\":\"Done\"}" }        # note: the variable is a STRING containing JSON
```

### 11.5 Column type catalog — read & write shapes

For each type: `type` string · write JSON shape · read shape (what comes back in `column_values { type text value }`) · real example · quirks. Writing `null` or `{}` clears most types.

#### 11.5.1 `text`
- **Write (simple):** `"Hello"` via `change_simple_column_value`
- **Write (JSON):** `{"text_column": "Hello"}` — just the string
- **Read:** `value = "\"Hello\""`, `text = "Hello"`
- Clear: `""`

#### 11.5.2 `long_text`
- **Write:** `{"long_text": {"text": "Line 1\nLine 2"}}`
- Simple string also works
- **Read:** `value = "{\"text\":\"Line 1\\nLine 2\",\"changed_at\":\"...\"}"`, `text = "Line 1\nLine 2"`
- Accepts newlines (since 2024-10 parser change)

#### 11.5.3 `numbers`
- **Write (simple):** `"42.5"` (string, not number)
- **Write (JSON):** `{"numbers_col": "42.5"}`
- No leading zeros: `9` not `09`
- Clear: `""`

#### 11.5.4 `status`
- **Write by label:** `{"status": {"label": "Done"}}`
- **Write by index (recommended, stable):** `{"status": {"index": 1}}`
- Simple string: `"Done"`
- Use `create_labels_if_missing: true` to create a label on the fly
- **Read:** `value = "{\"index\":1,\"post_id\":null,\"changed_at\":\"...\"}"`, `text = "Done"`
- Labels come from `settings_str.labels`: `{"0":"Working on it","1":"Done","2":"Stuck",...}`
- **Why prefer index:** label text can be renamed; index is stable

#### 11.5.5 `date`
- **Write:** `{"due": {"date": "2026-04-25", "time": "10:00:00"}}` (time optional)
- Simple string: `"2026-04-25"` or `"2026-04-25 10:00:00"`
- **Read:** `value = "{\"date\":\"2026-04-25\",\"time\":\"10:00:00\",\"icon\":null,\"changed_at\":\"...\"}"`
- **Timezone:** dates are stored in the account timezone; times are stored as UTC — convert explicitly in clients

#### 11.5.6 `people`
- **Write:** `{"owner": {"personsAndTeams": [{"id": 4616627, "kind": "person"}, {"id": 51166, "kind": "team"}]}}`
- Simple string: `"4616627,4616666"` (comma-separated user IDs)
- **IDs, not email addresses** — look up with `users(emails:["a@x.com"]) { id }` first
- Clear: `{}`

#### 11.5.7 `dropdown`
- **By labels:** `{"cats": {"labels": ["Cookie","Cupcake"]}}`
- **By IDs:** `{"cats": {"ids": [1, 2]}}`
- Cannot mix labels and IDs in the same write
- `create_labels_if_missing: true` supported
- Simple string: `"Cookie, Cupcake"` or `"1,2"`
- **Read:** `text = "Cookie, Cupcake"`, `value = "{\"ids\":[1,2],\"changed_at\":\"...\"}"`

#### 11.5.8 `timeline`
- **Write (JSON only):** `{"timeline_2": {"from": "2026-04-01", "to": "2026-04-15"}}`
- No simple-string form
- Inclusive range; YYYY-MM-DD
- Clear: `{}` or `null`

#### 11.5.9 `link`
- **Write:** `{"url_col": {"url": "https://x.com", "text": "Click me"}}`
- Simple string: `"https://x.com Click me"` (URL + space + label)

#### 11.5.10 `email`
- **Write:** `{"email": {"email": "a@b.com", "text": "Display"}}` — both keys required
- Simple string: `"a@b.com Display"`
- `text` defaults to the email if missing — send both to be safe

#### 11.5.11 `phone`
- **Write:** `{"phone": {"phone": "11231234567", "countryShortName": "US"}}`
- ISO Alpha-2 country, **uppercase**
- Simple string: `"11231234567 US"`
- Validated via Google's phone lib — invalid numbers rejected

#### 11.5.12 `location`
- **Write:** `{"loc": {"lat": "40.6892494", "lng": "-74.0445004", "address": "Statue of Liberty"}}`
- `lat`/`lng` are **strings**, not numbers
- `address` is free-form, not verified against coords
- Simple string: `"40.6892494 -74.0445004"` or with address appended

#### 11.5.13 `checkbox`
- **Check:** `{"done": {"checked": "true"}}` — string `"true"`, not boolean `true`
- **Uncheck:** send `null` (passing `"false"` is buggy — known issue, still checks the box)
- Simple string does not work reliably
- Clear = `null`

#### 11.5.14 `rating`
- **Write:** `{"stars": {"rating": 4}}` — integer 1..max (from `settings_str.max_rating`)
- Clear: `{}` or `null`

#### 11.5.15 `country`
- **Write:** `{"country": {"countryCode": "US", "countryName": "United States"}}`
- `countryCode` required; both should match

#### 11.5.16 `tags`
- **Write:** `{"tags": {"tag_ids": [295026, 295064]}}` — tag IDs only, integers
- First call `create_or_get_tag(tag_name: "urgent", board_id: 123)` to resolve names → IDs
- Private/shareable-board tags must be queried via `boards { tags { id name } }`, NOT root `tags`

#### 11.5.17 `hour`
- **Write:** `{"reminder": {"hour": 14, "minute": 30}}` — 24-hour, minute optional (default 0)
- **Read:** `{"hour":14,"minute":30,"changed_at":"..."}`

#### 11.5.18 `week`
- **Write (double-nested!):** `{"wk": {"week": {"startDate": "2026-04-13", "endDate": "2026-04-19"}}}`
- Exactly 7 days apart inclusive; must align with account's work-week start

#### 11.5.19 `world_clock`
- **Write:** `{"tz": {"timezone": "Europe/London"}}` — IANA timezone names only

#### 11.5.20 `dependency`
- **Write:** `{"deps": {"item_ids": [1587277166, 1587277190]}}`
- Target items must already exist on the same board; see https://developer.monday.com/api-reference/docs/working-with-dependency-column

#### 11.5.21 `board_relation` (connect boards)
- **Write:** `{"connect": {"item_ids": [12345, 23456]}}`
- **Target boards must be pre-connected** in the UI first — the API cannot establish board-to-board links, only add item links within existing connections

#### 11.5.22 `doc` (the Doc COLUMN type — NOT workspace docs)
This is the Phase 1 focus. It stores a **pointer** to a monday Doc.

- **Read:** `column_values { id type value text }` where `type = "doc"`. The `value` is JSON like `"{\"files\":[{\"linkToFile\":\"https://.../docs/12345\",\"name\":\"Spec\",\"assetId\":..., \"fileType\":\"MONDAY_DOC\",\"docId\":67890,\"objectId\":54321}]}"`. The useful pointer is `objectId` (or `docId` depending on version).
- **Two-step read to get content:**
  ```graphql
  query ($obj: [ID!]!) {
    docs(object_ids: $obj) {
      id object_id name doc_kind url workspace_id
      blocks { id type content parent_block_id }
    }
  }
  ```
- **Create doc attached to the column (when empty):**
  ```graphql
  mutation { create_doc(location: { board: { item_id: 123, column_id: "spec" } }) { id object_id } }
  ```
  This also populates the column value server-side.
- **Append content** to an existing doc:
  ```graphql
  mutation ($docId: ID!, $blocks: [CreateBlockInput!]!) {
    create_doc_blocks(doc_id: $docId, blocks: $blocks) { id }
  }
  ```
  Blocks are structured (`type: normal_text | heading | bullet_list | numbered_list | quote | code | divider | image | ...`) with JSON `content`.

**Versus workspace Docs (Phase 3):** workspace docs live in `docs(workspace_ids:) { ... }`, are created with `create_doc(location: { workspace: { workspace_id, name, kind }})`, and are NOT tied to an item.

#### 11.5.23 `file` / `assets`
- **Cannot set via `column_values`.**
- Upload via multipart POST to `https://api.monday.com/v2/file`:
  ```bash
  curl -X POST https://api.monday.com/v2/file \
    -H "Authorization: $TOKEN" \
    -F 'query=mutation add_file($file: File!, $itemId: ID!, $cid: String!) { add_file_to_column(item_id:$itemId, column_id:$cid, file:$file) { id } }' \
    -F 'variables={"itemId":1234,"cid":"files"}' \
    -F 'map={"image":"variables.file"}' \
    -F 'image=@./doc.pdf'
  ```
- Max 500 MB per upload. Do NOT manually set `Content-Type` — let the HTTP library set the multipart boundary.
- **Clear:** `{"clear_all": true}` (explicit, irreversible via API).
- Community-confirmed bug: the docs' example column id `"files"` sometimes returns 500 — always use the actual column id from `columns{ id type }`.

#### 11.5.24 Read-only types (cannot be written via API)
- `mirror` — use `MirrorValue` inline fragment, read `display_value`. Cannot filter on it in `items_page.query_params` (→ `InvalidColumnTypeException`).
- `formula` — use `FormulaValue.display_value`; limited to 5 formula columns per request, 10,000 formula values/min.
- `auto_number` — auto-assigned
- `item_id` — returns item's ID as a column-shaped value
- `creation_log` — creator + timestamp
- `last_updated` — last edit metadata
- `color_picker` — read-only via API; `ColorPickerValue.color` hex
- `progress`, `time_tracking`, `vote`, `button`, `subtasks` — no meaningful write support via `column_values`; use dedicated mutations (`create_subitem` for subtasks, etc.)

### 11.6 Clearing values — cheat sheet
| Column | Clear payload |
|---|---|
| text, numbers, long_text (simple) | `""` |
| Most JSON types (status, date, email, rating, timeline, people, dropdown, tags, etc.) | `{}` or `null` |
| file | `{"clear_all": true}` |
| checkbox | `null` (NOT `{"checked":"false"}`) |
| people (specific person) | `{"removed_person_or_team": {"id": 42, "kind": "person"}}` |

---

## 12. Subitems

Subitems live on a **hidden auto-generated board** linked via a `subtasks`/`subitems` column on the parent board. They are full `Item`s with their own column IDs (different from the parent).

- `subitems` is a field on `Item`, not a root query:
  ```graphql
  boards(ids: 123) { items_page {
    items { id name subitems { id name board { id } column_values { id text value } } }
  } }
  ```
- **Create:** `create_subitem(parent_item_id: ID!, item_name: String!, column_values: JSON, create_labels_if_missing: Boolean)` → `Item`. Returns the subitem; query `board { id }` on it to get the subitems board.
- **Update/delete:** reuse Item mutations (`change_column_value`, `archive_item`, etc.) against the subitem's own `board_id`, NOT the parent board.
- Subitem group IDs follow `subitems_of_<parent_item_id>` — useful for parent lookup when `parent_item` field is unavailable.
- `create_subitem` fails with `NoSubitemsColumnInThisBoard` if the parent board has no subitems column yet — create one subitem via UI first, or write to the `subtasks` column to materialize it (API cannot create the subitems column directly on a brand-new board).
- **Multi-level boards (2026-04 default):** no separate subitems board — parent and children share the same `board_id` and column structure; inspect `Board.hierarchy_type` = `multi_level`; up to 5 levels.

---

## 13. Updates (item comments)

**Query:**
```graphql
updates(ids: [ID!], limit: Int = 25, page: Int = 1): [Update]
# Also: items { updates { ... } }, boards { updates { ... } }
```
`Update` fields: `id, body, text_body, creator { id name }, creator_id, item_id, created_at, updated_at, replies { id body creator { id } }, assets { id url name }, likes { id }, pinned_to_top { item_id }, viewers { ... }`.

**Mutations:**
- `create_update(body: String!, item_id: ID, parent_id: ID)` — `parent_id` makes it a reply
- `edit_update(id: ID!, body: String!)`
- `delete_update(id: ID!)`
- `like_update(update_id: ID!)` / `unlike_update`
- `clear_item_updates(item_id: ID!)` → `Item`
- `pin_to_top(item_id: ID, update_id: ID!)` / `unpin_from_top`

**Gotchas:** `body` accepts HTML (not markdown). Page limit max 100 since 2025-04. Mentions use `<p>...</p><mention>...</mention>` HTML.

---

## 14. Other resources (phase 3)

### Users
`users(ids, kind, newest_first, limit, page, emails, name, non_active)` — `UserKind: all | non_guests | guests | non_pending`. Fields: `id, name, email, enabled, is_admin, is_guest, is_pending, is_view_only, created_at, last_activity, title, photo_thumb, teams, account`.

Mutations (2025-10+): `add_users_to_team`, `remove_users_from_team`, `update_multiple_users_as_(admins|guests|members|viewers)`, `deactivate_users`, `activate_users`, `update_email_domain`.

Gotcha: `users(emails:)` is case-sensitive and requires exact match. `users()` with no args hits complexity quickly.

### Teams
`teams(ids)` → `[Team { id name picture_url users { id name } owners { id } is_guest }]`. 2025-10+ mutations: `create_team(input, options)`, `delete_team`, `add_users_to_team`, `remove_users_from_team`, `assign_team_owners`, `remove_team_owners` — all return `ChangeTeamsMembershipResult { successful_users, failed_users { ... } }` with partial-success.

### Workspaces
`workspaces(ids, limit, page, kind, state)` — `kind: open | closed` (NOT `private`). Main Workspace cannot be deleted.

Mutations: `create_workspace(name, kind, description, account_product_id)`, `update_workspace(id, attributes: UpdateWorkspaceAttributesInput)`, `delete_workspace`, `add_users_to_workspace(kind: WorkspaceSubscriberKind!)`, `delete_users_from_workspace`, `add_teams_to_workspace`, `delete_teams_from_workspace`.

### Me & Account
`me` → the authenticated user. `account` is **only reachable through** `me { account { ... } }` or `users { account { ... } }` — no root `accounts` query. Fields: `id, name, slug, tier, country_code, first_day_of_the_week, active_members_count, logo, plan { max_users tier period version }, products { id kind }`.

### Folders
`folders(ids, workspace_ids, limit, page)` — requires `workspaces:read`. Max 3 nesting levels.

Mutations: `create_folder(name, workspace_id, color, parent_folder_id, custom_icon, font_weight)`, `update_folder(folder_id, name, account_product_id, position: {object_id, object_type, is_after})`, `delete_folder(folder_id)` — archives contained boards (30-day recovery) and deletes dashboards (30-day trash); only the creator can delete.

### Favorites
`favorites` — user's favorited boards/dashboards/workspaces/docs. Mutations to add/remove.

### Tags
`tags(ids)` — account-level only. For private/shareable boards use `boards { tags { id name color } }`. Mutation: `create_or_get_tag(tag_name, board_id)` returns existing or newly-created tag.

### Webhooks
`webhooks(board_id, app_webhooks_only)` → `[{ id board_id event config }]`.
Mutations: `create_webhook(board_id, url, event, config: JSON)` and `delete_webhook(id)`.

**Event types:** `change_column_value, change_specific_column_value, change_status_column_value, change_subitem_column_value, change_name, create_item, item_archived, item_deleted, item_moved_to_any_group, item_moved_to_specific_group, item_restored, create_subitem, change_subitem_name, move_subitem, subitem_archived, subitem_deleted, create_update, edit_update, delete_update, create_subitem_update`.

**Webhook handshake:** on `create_webhook`, monday POSTs a one-time JSON `{"challenge":"..."}` to your URL; your endpoint must echo `challenge` back within a short window or the webhook creation fails.

### Notifications
`create_notification(user_id: ID!, target_id: ID!, text: String!, target_type: NotificationTargetType!, internal: Boolean)` → `Notification { id text }`. `target_type`: `Post` (update/reply id) or `Project` (item or board id). Delivery is async; returned `id` is often `-1` and not queryable. Single user per call — loop for multi-user.

### Activity logs
Nested only: `boards(ids:) { activity_logs(limit, page, user_ids, column_ids, group_ids, item_ids, from, to) { id event data entity user_id created_at account_id } }`. `data` is a JSON string with before/after details. Retention: ~1 week on non-Enterprise; longer on Enterprise. No mutations. Audit-level events use separate admin-only `audit_logs`.

### Workspace docs (not the column type!)
`docs(ids, object_ids, workspace_ids, limit, page, order_by: created_at|used_at)` → `[Document { id object_id name doc_kind (public|private|share) created_at created_by url relative_url workspace_id blocks { id type content parent_block_id } }]`. `id` ≠ `object_id`; **`object_id` is the URL-visible numeric ID and appears inside `doc` column values**.

2026-03+ queries: `doc_version_history(doc_id, since, until)`, `doc_version_diff(doc_id, date, prev_date)`.

Mutations:
- `create_doc(location: CreateDocInput!)` where `CreateDocInput` is oneOf `{ workspace: { workspace_id, name, kind } }` or `{ board: { item_id, column_id } }`.
- `create_doc_block(type, doc_id, content: JSON, after_block_id, parent_block_id)` — single block
- `create_doc_blocks(doc_id, blocks: [CreateBlockInput!]!)` (2025-04+) — bulk; each `CreateBlockInput = { type, content, after_block_id, parent_block_id }`
- `update_doc_block(block_id, content: JSON)` · `delete_doc_block(block_id)`

Block types: `normal_text, heading, sub_heading, small_heading, bullet_list, numbered_list, quote, code, divider, image, layout, table, ...`.

### Aggregation API (2026-01)
Root `aggregate(board_id: ID!, group_by: [GroupByInput!], select: [SelectInput!], rules, limit)` → `[AggregateGroupByResult { group_by_values, values, value: JSON }]`. Functions: `SUM, AVERAGE, COUNT, COUNT_DISTINCT, MIN, MAX, MEDIAN`. Use for dashboards/reports without pulling all items.

### Validation rules (2025-04+)
Gradually rolling out to Pro/Enterprise. Server-side enforcement — violating item creates/edits are rejected with `RecordInvalidException`. Not supported on multi-level subitem boards.

Query: `validations`. Mutations: `create_validation_rule`, `update_validation_rule`, `delete_validation_rule`.

### Multi-level boards (GA Oct 2025; default 2026-04 RC)
Up to 5 subitem levels, rollup columns, `hierarchy_type: multi_level` on Board. Shares board_id across levels (no separate subitems board). `parent_item` field traverses up.

### Articles (2026-01)
Knowledge-base API for in-product articles. See https://developer.monday.com/api-reference/reference/articles.

### Notetaker (2026-01)
`notetaker.meetings` query — access monday's AI meeting summaries.

### Object relations (2026-01)
`object_relations` CRUD for `ALIAS` / `DEPENDENCY` relation types between entities.

---

## 15. Validation rules (client-side) & query optimization

### Optimizing API usage (per monday docs)
1. Request specific `columns(ids:)` instead of all columns.
2. Cache board schemas — column IDs/types don't change often; avoid re-fetching per call.
3. Use `change_multiple_column_values` not N × `change_column_value`.
4. Reuse GraphQL fragments for `column_values` field selections.
5. Use webhooks instead of polling.
6. Put `complexity { query before after }` in queries so you know your cost.
7. On Enterprise: use the API Analytics Dashboard and `platform_api.daily_analytics { by_day by_app by_user }` to monitor usage.

---

## 16. Quirks and footguns — condensed checklist

1. **No `Bearer` prefix** in `Authorization` header.
2. **`column_values` is a JSON-stringified string** even though GraphQL type is `JSON!` — use variables to avoid escape hell.
3. **Column IDs are per-board**, not globally unique — always fetch them from `boards { columns { id type } }`.
4. **Status: prefer index over label** — labels can be renamed.
5. **People/email columns need user IDs, not email addresses** — look up users first.
6. **Checkbox**: string `"true"`, uncheck with `null`, `"false"` is buggy.
7. **Week column** is double-nested: `{"wk": {"week": {"startDate","endDate"}}}`.
8. **File uploads** go to a different endpoint (`/v2/file`) with multipart; let HTTP lib set `Content-Type`.
9. **Board-relation/connect-boards** requires the board-to-board link to exist first — API can't create it.
10. **Mirror and formula columns can't be filtered** in `items_page.query_params`.
11. **Cursor lifetime is 60 minutes** — catch `CursorExpiredError` and restart.
12. **Root `items` with no IDs or >100 IDs is throttled to 1 call / 2 min.**
13. **`account_id` was dropped from default response envelope in 2025-04** — query `me { account { id } }`.
14. **`duplicate_board`/`duplicate_group` are 40/min.**
15. **Subitems** have a separate board with separate column IDs — mutating against the parent board_id fails with `ResourceNotFoundException`. Multi-level boards (2026-04+) unify this.
16. **Webhook creation does a one-time `challenge` POST** — your endpoint must echo it back.
17. **Timezones**: dates are account-local, times are UTC. Convert explicitly.
18. **Idempotency keys are NOT supported** — compensate client-side with natural-key guards.
19. **Include `request_id`** from `extensions` in all user-facing error messages.
20. **Always pin `API-Version`** — default is "Current" but that shifts quarterly.
````

---

## Mission 3 — Name options

Five candidates, ordered from strongest to weakest fit. Each is plausibly available as a PyPI package / Homebrew formula / short domain; verify before committing.

### 1. `mondo` — *pitch:* "Spanish for ‘world’ and a four-letter play on ‘monday’ — short, memorable, keyboard-friendly, unambiguously yours." Conveys scale without sounding corporate; pairs naturally with "power user" and doubles as a nice shell prompt alias.
```bash
mondo item create --board 1234 --name "Fix CI" --column status=Working --column owner=42
```

### 2. `weekday` — *pitch:* "A weekday-themed callout that positions the CLI as the daily-driver companion to monday.com — easy to explain to teammates and unmistakably about monday.com without ambiguity." Conveys "every day, not just Monday."
```bash
weekday item move --id 9876543210 --group sprint-16
```

### 3. `mondaisy` — *pitch:* "A playful mash-up of ‘monday’ + ‘daisy-chain’ hinting at composability — great for humans piping commands and agents chaining tool calls; memorable and unmistakably yours with no common-command collisions." (Pronounced "mon-daisy.")
```bash
mondaisy column set --item 555 --column status=Done -o json
```

### 4. `butlr` — *pitch:* "A five-letter concierge/butler metaphor — ‘your monday.com butler for humans and agents.’ Trendy vowel-drop naming (Flickr, Tumblr) makes the PyPI/domain almost certainly free, and the command reads like an assistant." Agent-friendly connotation baked in.
```bash
butlr board export --id 1234 --format xlsx --out board.xlsx
```

### 5. `mdy` — *pitch:* "The three-letter NYSE ticker for monday.com Ltd., repurposed as a terminal-minimalist alias — fastest possible to type in a shell, lands as a natural complement to `gh`, `az`, `gam`." Ideal if you value muscle-memory brevity above branding.
```bash
mdy item list --board 1234 -q "[?column_values[?id=='status'].text=='Stuck']"
```

**Tiebreaker recommendation:** `mondo` is the strongest all-rounder (short, pronounceable, memorable, no common-command collision, easy to alias, and has brand flexibility for Phase 2/3). `butlr` is the sharpest pick if you want the "AI agents welcome" positioning baked right into the name.