# mondo

Power-user CLI for the [monday.com](https://monday.com) GraphQL API — built in
the `az` / `gh` / `gam` style, for both senior admins at a terminal and AI agents
in automation pipelines.

Not a rebrand of monday's official `mapps`/`monday-cli` (which manages monday
*apps*). `mondo` is a wrapper for the *platform API*: boards, items, columns,
workspaces, users, docs, webhooks, etc.

> Status: Phase 1 MVP complete (auth, items, columns, doc column, raw GraphQL,
> output formatters, JMESPath). Phase 2 in progress: **board CRUD shipped (2a)**,
> column/group/workspace structural CRUD, export/import, and complexity
> metering queued. Phase 3 covers users/docs/webhooks and the rest.

---

## Installation

```bash
git clone https://github.com/marktguru/mondo.git
cd mondo
uv sync --all-extras
```

Quick smoke test:

```bash
export MONDAY_API_TOKEN="<paste your token>"
uv run mondo auth status
```

Native binaries via PyInstaller + a curl-pipe-bash installer + Homebrew tap are
planned for v1.0 (see [plan.md §15](plan.md)).

---

## Authentication

Four ways to supply your monday.com personal API token, in precedence order:

1. **`--api-token "..."`** flag (per-invocation; avoid — ends up in shell history)
2. **`MONDAY_API_TOKEN`** environment variable (best for one-off sessions & CI)
3. **OS keyring** via `mondo auth login` (recommended for daily use)
4. **Profile file** `~/.config/mondo/config.yaml` (for multiple accounts)

Get the token at **Profile avatar → Developers → API Token**.

```bash
# One-off:
export MONDAY_API_TOKEN="eyJhbGci..."

# Or stored in the OS keyring (macOS Keychain / Windows Credential Manager / libsecret):
uv run mondo auth login
```

---

## Commands

### Auth

```bash
mondo auth status                          # full identity + token source
mondo auth whoami                          # just the user + account
mondo auth login                           # store token in keyring
mondo auth logout                          # remove stored token
```

### Boards

```bash
mondo board list       [--state active|archived|deleted|all] [--kind public|private|share] \
                       [--workspace 42] [--order-by used_at|created_at] \
                       [--name-contains pager] [--name-matches '^team-\w+$'] \
                       [--limit 100] [--max-items 500]
mondo board get        --id 1234567890
mondo board create     --name "Roadmap" --kind public [--workspace 42] [--description …] \
                       [--owner 7] [--subscriber 8] [--empty]
mondo board update     --id 1234567890 --attribute name --value "Renamed"
mondo board archive    --id 1234567890                   # reversible (30 days)
mondo board delete     --id 1234567890 --hard --yes      # permanent
mondo board duplicate  --id 1234567890 --type duplicate_board_with_pulses_and_updates \
                       [--name "Copy"] [--workspace 42] [--keep-subscribers]
```

monday's `boards` query has no server-side name filter; `--name-contains` and
`--name-matches` are applied client-side after page-based fetch.

### Items

```bash
mondo item list   --board 1234567890 [--max-items 50] [--filter status=Done] [--order-by date4,desc]
mondo item get    --id 987 [--include-updates] [--include-subitems]
mondo item create --board 1234567890 --name "Fix CI" \
                  --column status=Working --column owner=42 --column due=2026-04-25
mondo item rename    --id 987 --board 1234567890 --name "New title"
mondo item archive   --id 987                            # reversible (30-day monday recovery)
mondo item delete    --id 987 --hard --yes               # permanent
mondo item move      --id 987 --group topics_two         # between groups, same board
mondo item duplicate --id 987 --board 1234567890 --with-updates
```

### Columns

```bash
mondo column list     --board 1234567890
mondo column get      --item 987 --column status         # codec-rendered display
mondo column get      --item 987 --column status --raw   # {id, type, value, text}
mondo column set      --item 987 --column status --value Done
mondo column set      --item 987 --column tags   --value urgent,blocked   # names auto-resolve
mondo column set-many --item 987 --values '{"text":"Hi","due":{"date":"2026-04-25"}}'
mondo column clear    --item 987 --column status
```

**Smart shorthand** — no raw JSON needed for common cases. Dispatched via a
codec registry (22 writable column types):

| Column type | `--value` shorthand | Expands to |
|---|---|---|
| `text` | `Hello` | `"Hello"` |
| `numbers` | `42.5` | `"42.5"` |
| `status` | `Done` or `#1` | `{"label":"Done"}` / `{"index":1}` |
| `date` | `2026-04-25` | `{"date":"2026-04-25"}` |
| `date` | `2026-04-25T10:00` | `{"date":"…","time":"10:00:00"}` |
| `timeline` | `2026-04-01..2026-04-15` | `{"from":"…","to":"…"}` |
| `week` | `2026-W16` | `{"week":{"startDate":"…","endDate":"…"}}` |
| `hour` | `14:30` | `{"hour":14,"minute":30}` |
| `people` | `42,51,team:7` | `{"personsAndTeams":[…]}` |
| `dropdown` | `Cookie,Cupcake` | `{"labels":[…]}` |
| `email` | `a@b.com,"Display"` | `{"email":"…","text":"…"}` |
| `phone` | `+19175998722,US` | `{"phone":"…","countryShortName":"US"}` |
| `link` | `https://x.com,"click me"` | `{"url":"…","text":"…"}` |
| `location` | `40.68,-74.04,"NYC"` | `{"lat":"…","lng":"…","address":"…"}` |
| `country` | `US` | `{"countryCode":"US","countryName":"United States"}` |
| `checkbox` | `true` / `false` / `clear` | `{"checked":"true"}` / `null` |
| `rating` | `4` | `{"rating":4}` |
| `tags` | `urgent,blocked` | `{"tag_ids":[…]}` (names resolved via `create_or_get_tag`) |
| `board_relation` | `12345,23456` | `{"item_ids":[…]}` |
| `dependency` | `12345,23456` | `{"item_ids":[…]}` |
| `world_clock` | `Europe/London` | `{"timezone":"Europe/London"}` |

Force raw JSON with `--raw`: `mondo column set --item 1 --column status --value '{"index":3}' --raw`.

### `doc` columns

Monday's `doc` column holds a pointer to a workspace Doc (structured blocks,
not a file). `mondo column doc` reads and writes its content as Markdown.

```bash
mondo column doc get    --item 987 --column spec                       # rendered as Markdown
mondo column doc get    --item 987 --column spec --format raw-blocks   # raw block JSON
mondo column doc set    --item 987 --column spec --from-file spec.md   # create or append
mondo column doc append --item 987 --column spec --markdown "- new bullet"
mondo column doc clear  --item 987 --column spec                       # unlinks the doc pointer
```

Supported markdown blocks: headings h1–h3, paragraphs, bullet / numbered lists,
blockquotes, fenced code (with language), horizontal rules.

### Raw GraphQL passthrough

```bash
# Inline:
mondo graphql 'query { me { id name } }'

# With variables:
mondo graphql 'query ($ids:[ID!]!){items(ids:$ids){id name}}' --vars '{"ids":[1,2]}'

# From a file or stdin:
mondo graphql @query.graphql
cat mutation.graphql | mondo graphql -
```

---

## Output formatting

```
--output,-o {table|json|jsonc|yaml|tsv|csv|none}   # default: table on TTY, json otherwise
--query,-q <jmespath>                              # applied *before* formatting
```

Global flags are accepted **anywhere on the command line** (az-style):

```bash
mondo item list --board 42 -o table -q '[].{id:id,name:name}'
mondo -o table -q '[].{id:id,name:name}' item list --board 42   # also works
```

Practical recipes:

```bash
# Find boards by name (server has no name filter; JMESPath handles it):
mondo graphql 'query { boards(limit:200) { id name items_count } }' \
    -q "data.boards[?contains(name,'Pager')]" -o table

# Extract a scalar with --output none for shell pipelines:
count=$(mondo item list --board 42 -q "length(@)" -o none)

# Export as CSV:
mondo item list --board 42 -q '[].{id:id,name:name,state:state}' -o csv > items.csv
```

---

## Configuration

Lives at `~/.config/mondo/config.yaml` (or `$XDG_CONFIG_HOME/mondo/config.yaml`).
Env-var expansion (`${VAR}`) is supported.

```yaml
default_profile: personal
api_version: "2026-01"

profiles:
  personal:
    api_token_keyring: "mondo:personal"      # read from OS keyring
    default_board_id: 1234567890
    output: table

  work:
    api_token: ${WORK_MONDAY_TOKEN}          # read from env
    api_version: "2025-10"                   # profile override
    default_workspace_id: 42
```

Pick a profile with `--profile work` or `MONDO_PROFILE=work`.

---

## Global flags

```
--profile NAME / MONDO_PROFILE              Select config profile
--api-token TOKEN / MONDAY_API_TOKEN        Override API token (flag wins over env)
--api-version YYYY-MM / MONDAY_API_VERSION  Pin API version (default: 2026-01)
--output,-o {table|json|jsonc|yaml|tsv|csv|none}
--query,-q <jmespath>                       JMESPath projection before formatting
--verbose,-v                                INFO-level logging to stderr
--debug                                     Full request/response to stderr (token redacted)
--yes,-y                                    Skip confirmation prompts
--dry-run                                   Print the GraphQL that would be sent, don't send
--version,-V                                Show version and exit
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic error |
| 2 | usage error |
| 3 | auth error |
| 4 | rate / complexity exhausted after retries |
| 5 | validation error (bad column value, unknown column id, ...) |
| 6 | not found |
| 7 | network / transport error |

Agents and scripts should check these codes; everything that goes to stdout is
machine-parseable JSON when stdout isn't a TTY.

---

## Development

```bash
uv sync --all-extras         # install deps + dev tools
uv run pytest                # 440 tests, includes CLI E2E via pytest-httpx
uv run ruff check src tests  # lint
uv run ruff format src tests # format
uv run mypy src              # strict type-check
```

See [plan.md](plan.md) for the full roadmap and [monday-api.md](monday-api.md)
for the API reference this CLI targets.

## License

MIT.
