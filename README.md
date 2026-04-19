# mondo

Power-user CLI for the [monday.com](https://monday.com) GraphQL API — built in
the `az` / `gh` / `gam` style, for both senior admins at a terminal and AI agents
in automation pipelines.

Not a rebrand of monday's official `mapps`/`monday-cli` (which manages monday
*apps*). `mondo` is a wrapper for the *platform API*: boards, items, columns,
workspaces, users, docs, webhooks, etc.

> Status: **Phases 1, 2, and 3 complete.** Full command surface: auth, items,
> subitems, columns (+ structural CRUD), groups, boards, workspaces, users,
> teams, workspace docs, webhooks, files, activity, folders, favorites, tags,
> notifications, aggregations, validation rules, bulk import/export, raw
> GraphQL, and session complexity metering. Ships with an agent-facing help
> system (`mondo help`, `mondo help --dump-spec`) bundled inside the binary.

---

## Installation

### Homebrew (macOS, Linux) — recommended

```bash
brew install zoltanf/mondo/mondo
```

That single command is shorthand for:

```bash
brew tap zoltanf/mondo    # add the zoltanf/homebrew-mondo tap
brew install mondo        # install the right binary for your OS/arch
```

Homebrew picks the correct artifact for your platform (Apple Silicon macOS, or
arm64/x86_64 on Linux), puts `mondo` on your `PATH`, and — importantly on macOS
— **strips Apple's quarantine attribute automatically**, so you don't run into
the Gatekeeper warning described below.

> **Intel Macs are not supported** by the binary builds. `brew install` will
> refuse with a clean "requires arm64 architecture" message. If you're still on
> Intel hardware, install from source (see [From source](#from-source) below).

Upgrade later with:

```bash
brew upgrade mondo
```

Uninstall:

```bash
brew uninstall mondo
brew untap zoltanf/mondo   # optional
```

### Direct download (all platforms)

Grab a pre-built binary for your OS/arch from the [Releases page][releases]:

| Platform           | Asset                                     |
|--------------------|-------------------------------------------|
| macOS (Apple Si.)  | `mondo-<ver>-darwin-arm64.tar.gz`         |
| Linux (x86_64)     | `mondo-<ver>-linux-x86_64.tar.gz`         |
| Linux (arm64)      | `mondo-<ver>-linux-arm64.tar.gz`          |
| Windows (x86_64)   | `mondo-<ver>-windows-x86_64.zip`          |

Intel Mac users: no pre-built binary — install [from source](#from-source).

Then:

```bash
# macOS / Linux
tar -xzf mondo-<ver>-<os>-<arch>.tar.gz
sudo mv mondo /usr/local/bin/
mondo --version
```

```powershell
# Windows
Expand-Archive mondo-<ver>-windows-x86_64.zip
# move mondo.exe somewhere on your PATH
mondo --version
```

#### macOS: working around Gatekeeper ("unidentified developer")

The macOS binaries are currently **unsigned** and **unnotarized**. This is only
an issue for **direct downloads** — `brew install` handles it for you, see
above.

When you run a directly-downloaded `mondo` for the first time you'll see one
of these dialogs:

- *"`mondo` cannot be opened because the developer cannot be verified."*
- *"`mondo` is damaged and can't be opened. You should move it to the Trash."*
  (confusingly, this is also Gatekeeper — it's not actually damaged)

Pick one of the fixes below.

**Fix 1 — one-liner in Terminal (recommended):**

```bash
xattr -d com.apple.quarantine ./mondo
./mondo --version
```

The `com.apple.quarantine` xattr is what macOS sets on anything downloaded
through a browser. Removing it tells Gatekeeper the binary is locally
provenanced.

**Fix 2 — GUI, per-binary:**

1. In Finder, locate `mondo`, **Control-click** it, choose **Open**.
2. Confirm **Open** in the dialog that appears.
3. Subsequent runs from Terminal then work without further prompts.

**Fix 3 — "damaged and can't be opened":**

If Fix 2 doesn't offer an **Open** button and you only see the *damaged* error,
Fix 1 is the answer — that message is how recent macOS versions surface the
same quarantine check.

**Why not sign the binary?** Signing + notarizing requires a $99/yr Apple
Developer account. For now we ship unsigned binaries to keep releases free.
If you want the friction gone entirely, `brew install` is the easy path.

### From source

```bash
git clone https://github.com/zoltanf/mondo.git
cd mondo
uv sync --all-extras
uv run mondo --version
```

Quick smoke test:

```bash
export MONDAY_API_TOKEN="<paste your token>"
uv run mondo auth status
```

[releases]: https://github.com/zoltanf/mondo/releases

---

## Help & discovery

The binary is self-documenting — no internet or source checkout required:

```bash
mondo help                           # list every bundled topic
mondo help agent-workflow            # AI / automation onboarding guide
mondo help codecs                    # column-value shorthand reference
mondo help exit-codes                # exit-code table + retry guidance
mondo help --dump-spec -o json       # full command tree as JSON
```

Every subcommand carries runnable examples in its `--help` page:

```bash
mondo item create --help             # shows flag table + 4 runnable examples
mondo column set --help              # codec shorthand examples
mondo board duplicate --help         # schema-preserving + schema-renaming forms
```

**For AI agents and scripts:** `mondo help --dump-spec -o json` emits the
entire command tree — every flag, type, required-ness, enum choices,
docstring, example, and exit-code table — as one JSON blob. Ingest it once;
plan many invocations without parsing terminal help text. Exit codes are
narrow and stable (3=auth, 4=rate, 5=validation, 6=not-found, 7=network),
so retry logic can branch on the code rather than scraping stderr.

Bundled topics:

| Topic             | What's inside                                           |
|-------------------|---------------------------------------------------------|
| `agent-workflow`  | Short onboarding for AI agents and CI pipelines         |
| `auth`            | Token resolution chain + `mondo auth login`/`logout`    |
| `codecs`          | `--column COL=VAL` parsing table for every column type  |
| `complexity`      | monday's per-minute budget, retry guidance, debug logs  |
| `exit-codes`      | Exit codes 0–7 with retry/retry-not guidance            |
| `filters`         | Server-side `--filter` + client-side JMESPath recipes   |
| `graphql`         | Using `mondo graphql` as the escape hatch               |
| `output`          | `--output` / `--query` formatting + projection          |
| `profiles`        | Multi-account `config.yaml` + env-var interpolation     |

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

### Complexity metering

```bash
mondo complexity status                   # cheap query → print the live budget
mondo --debug item list --board 42        # logs `complexity drain: cost=… budget=…/…` per call
```

Every query sent by `mondo` is transparently rewritten to ask monday for
the current [complexity counters](https://developer.monday.com/api-reference/docs/complexity),
feeding a session-local meter exposed through `client.meter` (for agents) and
`mondo complexity status` (for humans). The raw-passthrough `mondo graphql`
is exempt — what you type is what gets sent.

### Import

```bash
# CSV round-trip (matches the export schema: name, group, plus column titles)
mondo import board --board 1234567890 --from items.csv

# With header-to-column-id overrides:
mondo import board --board 1234567890 --from items.csv --mapping mapping.yaml

# Default group for rows without a `group` column:
mondo import board --board 1234567890 --from items.csv --group topics

# Skip rows whose name already exists on the board (O(board size) pre-fetch):
mondo import board --board 1234567890 --from items.csv --idempotency-name

# Dry-run — prints what would be created without any mutations:
mondo --dry-run import board --board 1234567890 --from items.csv
```

Column values use the same codec registry as `mondo item create` — so CSV
cells like `Done`, `2026-04-25`, `urgent,blocked` parse into the right JSON.
Each row emits a result record (`created`/`skipped`/`failed`/`dry-run`); a
single failing row does not abort the run, and the command exits `1` if any
row failed.

`mapping.yaml` schema:

```yaml
columns:
  Stage: status          # CSV header: monday column_id
  Due Date: date4
name_column: name        # optional; defaults to 'name'
group_column: group      # optional; defaults to 'group'
```

### Export

```bash
mondo export board --board 1234567890 --format csv                        # to stdout
mondo export board --board 1234567890 --format json --out board.json
mondo export board --board 1234567890 --format xlsx --out board.xlsx      # required for xlsx
mondo export board --board 1234567890 --format md   --include-subitems    # markdown pipe table
mondo export board --board 1234567890 --format tsv  --max-items 1000
```

Formats: `csv | tsv | json | xlsx | md`. Column headers are the board's column
titles (archived columns are dropped). With `--include-subitems`, the CSV /
TSV emit a second blank-line-separated block, JSON gets a `subitems` array,
Markdown gets a `### Subitems` section, and XLSX gets a second worksheet.

### Users

```bash
mondo user list   [--kind all|non_guests|guests|non_pending] [--email a@x.com] \
                  [--name "Alice"] [--non-active] [--newest-first] [--limit 100]
mondo user get    --id 42

mondo user deactivate      --user 1 [--user 2] --yes
mondo user activate        --user 1 [--user 2]
mondo user update-role     --user 1 --role admin|member|guest|viewer
mondo user add-to-team     --team 7 --user 1 [--user 2]
mondo user remove-from-team --team 7 --user 1
```

`--role` hides four distinct server mutations (`update_multiple_users_as_admins`
/ `_members` / `_guests` / `_viewers`). `--email` is case-sensitive (monday
quirk). Each of the mass-change mutations returns `{successful_users, failed_users}`
— mondo surfaces the full partial-success payload.

### Me & account

```bash
mondo me        # authenticated user (teams + account embedded)
mondo account   # the account (tier, plan, products, active_members_count)
```

### Notifications

```bash
mondo notify send --user 42 --target 100 --target-type Project --text "FYI"
mondo notify send --user 42 --target 555 --target-type Post     --text "reply" --internal
```

monday's notification mutation is single-user; loop for batches. Delivery is
async — the returned `id` is often `-1` and not queryable. `target_type` is
case-sensitive: `Project` for item/board IDs, `Post` for updates/replies.

### Aggregations

```bash
mondo aggregate board --board 1234567890 --select COUNT:*
mondo aggregate board --board 1234567890 --group-by status --select COUNT:* --select SUM:price
mondo aggregate board --board 1234567890 --group-by owner --select AVERAGE:duration \
  --filter '{"rules":[{"column_id":"status","operator":"any_of","compare_value":["Done"]}]}'
```

Requires API version 2026-01+. Functions: `SUM | AVERAGE | COUNT |
COUNT_DISTINCT | MIN | MAX | MEDIAN`. `COUNT:*` counts all rows (translated
to monday's `COUNT_ITEMS`); any other `FUNCTION:*` is rejected client-side.
Output is a list of flattened `{alias: value}` dicts — one per group (or one
total when `--group-by` is omitted). Use instead of pulling every item when
you only need totals.

### Validation rules (Pro/Enterprise)

```bash
mondo validation list   --board 1234567890
mondo validation create --board 1234567890 --column status --rule-type REQUIRED
mondo validation create --board 1234567890 --column numbers --rule-type MIN_VALUE \
                        --value '{"min":10}' --description "Non-zero price"
mondo validation update --id 1 --description "Updated"
mondo validation delete --id 1 --yes
```

Violating item creates/edits raise `RecordInvalidException`. Not supported on
multi-level subitem boards.

### Activity logs

```bash
mondo activity board --board 1234567890 \
  [--since 2026-04-01T00:00:00Z] [--until 2026-04-18T23:59:59Z] \
  [--user 42 --user 43] [--item 100] [--group topics] [--column status] \
  [--limit 100] [--max-items 5000]
```

Activity logs are nested under `boards` — no root query. Retention is
~1 week on non-Enterprise tiers.

### Folders

```bash
mondo folder list     [--workspace 42]
mondo folder get      --id 7
mondo folder create   --workspace 42 --name "Eng" [--color DONE_GREEN] [--parent 3]
mondo folder update   --id 7 [--name …] [--color …] \
                      [--position '{"object_id":8,"object_type":"Folder","is_after":true}']
mondo folder delete   --id 7 --hard --yes     # archives contained boards
```

Max 3 nesting levels per monday. Only the creator can delete a folder.

### Favorites

```bash
mondo favorite list   # boards, dashboards, workspaces, docs the current user has favorited
```

Read-only in mondo today; add/remove mutations are queued for 3i pending
SDL verification.

### Tags

```bash
mondo tag list   [--id 123 --id 456]
mondo tag get    --id 123
mondo tag create-or-get --name urgent --board 1234567890   # idempotent
```

`tags(ids)` is account-scoped (public tags). Board-private tags live on
`board.tags` — use `mondo board get --id <board>` to see them.

### Files

```bash
mondo file upload   --file report.pdf --item 1234567890 --column files
mondo file upload   --file shot.png --target update --update 555
mondo file download --asset 42                      # writes to ./<asset_name>
mondo file download --asset 42 --out /tmp/x.pdf
```

Uploads go to `/v2/file` as multipart (max 500 MB per file, monday's cap).
Downloads resolve the asset's URL via `assets(ids)` then stream the bytes
to disk — works for `file`, image, and video attachments.

### Webhooks

```bash
mondo webhook list   --board 1234567890 [--app-only]
mondo webhook create --board 1234567890 --url https://example.com/hook \
                     --event create_item [--config '{"columnId":"status"}']
mondo webhook delete --id 123 --yes
```

Events: `change_column_value`, `change_specific_column_value`, `change_status_
column_value`, `change_subitem_column_value`, `change_name`, `create_item`,
`item_archived`, `item_deleted`, `item_moved_to_any_group`, `item_moved_to_
specific_group`, `item_restored`, `create_subitem`, `change_subitem_name`,
`move_subitem`, `subitem_archived`, `subitem_deleted`, `create_update`,
`edit_update`, `delete_update`, `create_subitem_update`.

monday performs a one-time challenge handshake against `--url` when the
webhook is created — your endpoint must echo the `challenge` JSON field or
creation fails. mondo just sends the mutation; the handshake is your
server's responsibility.

### Workspace docs

Distinct from the `doc` *column* type (`mondo column doc`): these are
standalone documents inside a workspace, built from a block tree.

```bash
mondo doc list           [--workspace 42] [--object-id 77] [--order-by used_at] \
                         [--limit 100] [--max-items 500]
mondo doc get            --id 7           # internal id
mondo doc get            --object-id 77   # URL-visible id
mondo doc get            --id 7 --format markdown    # render blocks → markdown
mondo doc create         --workspace 42 --name "Spec" --kind public

mondo doc add-content    --doc 7 --from-file spec.md         # bulk markdown → blocks
mondo doc add-block      --doc 7 --type normal_text \
                         --content '{"deltaFormat":[{"insert":"hi"}]}' \
                         [--after <block-id>] [--parent-block <block-id>]
mondo doc update-block   --id <block-id> --content '<json>'
mondo doc delete-block   --id <block-id>
```

`add-content` reuses the Phase-1f markdown converter (headings h1-h3,
paragraphs, bullet / numbered lists, blockquotes, fenced code, horizontal
rules). monday has no top-level `delete_doc` mutation — delete individual
blocks, or delete via the monday UI.

### Updates (item comments)

```bash
mondo update list                                     # account-wide, paginated
mondo update list   --item 1234567890 [--max-items 50]
mondo update get    --id 555
mondo update create --item 1234567890 --body "<p>FYI</p>"
mondo update create --item 1234567890 --from-file note.html
mondo update reply  --parent 555 --body "<p>re</p>"
mondo update edit   --id 555 --body "<p>new body</p>"
mondo update delete --id 555 --yes
mondo update like   --id 555
mondo update unlike --id 555
mondo update pin    --id 555 [--item 1234567890]
mondo update unpin  --id 555 [--item 1234567890]
mondo update clear  --item 1234567890 --yes          # nuke ALL updates on an item
```

monday treats update `body` as **HTML** (not markdown) — `<p>`, `<mention>`,
inline `<a>`/`<b>`/`<i>` etc. are supported. Page size is capped at 100.

### Subitems

```bash
mondo subitem list    --parent 1234567890
mondo subitem get     --id 9876543210
mondo subitem create  --parent 1234567890 --name "Sub task" \
                      [--subitems-board 999 --column status9=Done] \
                      [--create-labels-if-missing]
mondo subitem rename  --id 9876 --board 999 --name "New title"
mondo subitem move    --id 9876 --group subitems_of_1234567890
mondo subitem archive --id 9876 --yes
mondo subitem delete  --id 9876 --hard --yes
```

Subitems live on a separate hidden board (§12). Pass `--subitems-board <id>`
on `create` to get codec dispatch on `--column` values — the id surfaces on
`mondo subitem list`'s output as `.[0].board.id`. Without it, `--column`
values are sent verbatim.

### Teams

```bash
mondo team list   [--id 1 --id 2]           # filter to specific IDs
mondo team get    --id 7
mondo team create --name "Platform" [--subscriber 1 --subscriber 2] \
                  [--parent-team 3] [--guest-team] [--allow-empty]
mondo team delete --id 7 --hard --yes       # permanent

mondo team add-users      --id 7 --user 1 [--user 2]
mondo team remove-users   --id 7 --user 1
mondo team assign-owners  --id 7 --user 1   # promote to team owner
mondo team remove-owners  --id 7 --user 1
```

All mass-change mutations return `{successful_users, failed_users}` — mondo
surfaces the full partial-success payload so agents can retry failures.

### Workspaces

```bash
mondo workspace list          [--kind open|closed] [--state active|archived|deleted|all] \
                              [--limit 100] [--max-items 500]
mondo workspace get           --id 7
mondo workspace create        --name "Engineering" [--kind open|closed] [--description …] \
                              [--product-id 3]
mondo workspace update        --id 7 [--name …] [--description …] [--kind closed]
mondo workspace delete        --id 7 --hard --yes    # Main Workspace cannot be deleted

mondo workspace add-user      --id 7 --user 42 [--user 43] [--kind subscriber|owner]
mondo workspace remove-user   --id 7 --user 42
mondo workspace add-team      --id 7 --team 11 [--team 12] [--kind subscriber|owner]
mondo workspace remove-team   --id 7 --team 11
```

### Groups

```bash
mondo group list       --board 1234567890
mondo group create     --board 1234567890 --name "Planning" [--color "#00c875"] \
                       [--relative-to topics] [--position-relative-method after_at]
mondo group rename     --board 1234567890 --id topics --title "Workstreams"
mondo group update     --board 1234567890 --id topics --attribute color --value "#ff007f"
mondo group reorder    --board 1234567890 --id topics (--after g2 | --before g1 | --position 3)
mondo group duplicate  --board 1234567890 --id topics [--title "Topics 2"] [--add-to-top]
mondo group archive    --board 1234567890 --id topics --yes
mondo group delete     --board 1234567890 --id topics --hard --yes   # cascades to items
```

`--color` accepts only monday's palette hex codes (e.g. `#00c875`, `#ff007f`);
other values are rejected client-side. monday blocks deletion of the last
remaining group on a board with `DeleteLastGroupException`.

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
mondo item move-to-board --id 987 --to-board 2345 --to-group topics \
                      [--column-mapping status=state] [--column-mapping date4=due] \
                      [--column-mapping notes=]        # '=' with empty target drops the column
mondo item duplicate --id 987 --board 1234567890 --with-updates
```

`item move-to-board` requires a destination group. Pass `--column-mapping
SRC=DST` (repeatable) when the source and target boards have different
column IDs; unmapped source columns are dropped. `--subitem-column-mapping`
does the same for the moved item's subitems.

### Columns

```bash
# Read & write values
mondo column list     --board 1234567890
mondo column get      --item 987 --column status         # codec-rendered display
mondo column get      --item 987 --column status --raw   # {id, type, value, text}
mondo column set      --item 987 --column status --value Done
mondo column set      --item 987 --column tags   --value urgent,blocked   # names auto-resolve
mondo column set-many --item 987 --values '{"text":"Hi","due":{"date":"2026-04-25"}}'
mondo column clear    --item 987 --column status

# Structural (2b)
mondo column create          --board 1234567890 --title "Priority" --type status \
                             --defaults '{"labels":{"1":"High","2":"Medium"}}' \
                             [--id priority] [--after status] [--description "…"]
mondo column rename          --board 1234567890 --id status --title "Workflow"
mondo column change-metadata --board 1234567890 --id status --property description --value "…"
mondo column delete          --board 1234567890 --id status --yes
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
uv run pytest                # 655 tests, includes CLI E2E via pytest-httpx
uv run ruff check src tests  # lint
uv run ruff format src tests # format
uv run mypy src              # strict type-check
```

## Releasing

Releases are fully automated once you push a `v*` tag. The local driver script
handles the version bump, commit, tag, and push — everything after that runs in
GitHub Actions.

### Cut a release

From a clean `main` that is in sync with `origin`:

```bash
./scripts/release.sh 0.4.0
```

What this does, in order:

1. Verifies the working tree is clean, you're on `main`, and you're in sync with `origin/main`.
2. Rewrites `__version__` in [src/mondo/version.py](src/mondo/version.py) and `version = "..."` in [pyproject.toml](pyproject.toml).
3. Runs `uv sync` and `uv run pytest -m "not integration"` (skip with `--skip-tests` if you know what you're doing).
4. Commits the bump as `chore(release): v0.4.0`.
5. Creates an annotated tag `v0.4.0`.
6. Pushes `main` and the tag to `origin`.
7. Prints the Actions URL so you can watch the build.

### What runs in CI

Pushing the tag triggers [.github/workflows/release.yml](.github/workflows/release.yml), which:

1. **Builds five binaries in parallel** — macOS (arm64 + Intel), Linux (x86_64 + arm64), Windows (x86_64) — using PyInstaller on matching GitHub runners. Each binary is smoke-tested with `--version` and `--help` before being archived.
2. **Creates the GitHub Release** — attaches all five archives to a new Release at `https://github.com/zoltanf/mondo/releases/tag/v<ver>` with auto-generated notes from commit history.
3. **Updates the Homebrew tap** — regenerates `Formula/mondo.rb` in [zoltanf/homebrew-mondo][tap] with the new version and SHA256s, then pushes. Users get the new binary on their next `brew upgrade mondo`.

End-to-end latency is roughly 6–10 minutes depending on runner availability.

### Pre-releases

For a dry-run before a real release, use a pre-release suffix:

```bash
./scripts/release.sh 0.4.0-rc1
```

The script accepts any semver-compatible pre-release identifier
(`X.Y.Z-<anything>`). GitHub marks the release as a pre-release automatically
when the tag contains a `-`, and the Homebrew formula is still updated — use an
RC tag only when you don't mind `brew upgrade` picking it up.

### Prerequisites (one-time, already set up)

These are already in place for this repo — listed for reference in case you
fork:

- Public repo `zoltanf/homebrew-mondo` (the tap).
- Fine-grained PAT with `contents: write` on the tap repo, stored as the
  `HOMEBREW_TAP_TOKEN` secret on `zoltanf/mondo`.
- [LICENSE](LICENSE) file at repo root (Homebrew's audit requires it).

[tap]: https://github.com/zoltanf/homebrew-mondo

## Documentation

Additional docs live under [`docs/`](docs/):

- [docs/plan.md](docs/plan.md) — full product roadmap and phase breakdown.
- [docs/monday-api.md](docs/monday-api.md) — monday.com GraphQL API reference this CLI targets.
- [docs/help-system.md](docs/help-system.md) — design notes for `mondo help`, per-command epilogs, and `--dump-spec`.
- [docs/project codename mondo.md](<docs/project codename mondo.md>) — original design doc / product vision.
- [docs/implementation-phase-1.md](docs/implementation-phase-1.md) — Phase 1 implementation notes (auth, items, columns, `doc` columns).
- [docs/implementation-phase-2.md](docs/implementation-phase-2.md) — Phase 2 implementation notes (boards, workspaces, users, teams, docs, webhooks, import/export).
- [docs/implementation-phase-3.md](docs/implementation-phase-3.md) — Phase 3 implementation notes (files, activity, folders, favorites, tags, notifications, aggregations, validation).

## License

MIT.
