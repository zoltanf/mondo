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
| **3h (help system)** | Agent-facing help surface: per-command runnable examples in Typer epilogs, `mondo help <topic>` with bundled markdown, `mondo help --dump-spec -o json` machine contract. See [help-system.md](help-system.md). |

## 3. Technology choices

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.11+ | user preference, matches GAM distribution model |
| Dependency & project manager | **uv** + `pyproject.toml` (src layout, PEP 621) | user familiarity, 10-100× faster than pip, reproducible `uv.lock` |
| CLI framework | **Typer** (built on Click) | type-hint driven,  `app.add_typer()` is the cleanest deep-nesting pattern  in Python, first-class shell completion, native Rich integration. Fallback to Click via `typer.main.get_command()` if a plugin needs it.  |
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
    If column already points to a doc: loop `create_doc_block` per markdown block (monday no longer exposes a bulk `create_doc_blocks`), chaining `after_block_id` to preserve order.
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

**Phase 4 — local directory cache (performance)**
```
mondo cache status|refresh|clear [boards|workspaces|users|teams|all]
# Transparent serving of `mondo {board,workspace,user,team} list` from a
# per-profile on-disk cache, plus `--name-fuzzy` matching.
# Full contract: docs/caching.md
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
2. Whether to embed a vendored MCP server mode (`mondo mcp serve`) so the binary doubles as an MCP provider for agents — logical Phase 3 bonus given monday already ships one (https://monday.com/w/mcp). (Partial resolution: `mondo help --dump-spec -o json` already gives agents a consumable machine contract; MCP wraps this for tighter Claude/OpenAI tool-calling integration.)
3. File-upload streaming: stream from stdin when `--file -` to support large uploads without temp files.
4. Cache schema introspection (`/v2/get_schema?version=...`) in `~/.cache/mondo/` and use it for client-side arg validation.