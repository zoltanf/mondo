# Columns

Typed fields on a board. Read with `column list` / `column get`; write with `column set` (per item) or `--column k=v` on `item create`. Doc-column ops live in `references/docs.md`.

## List columns on a board

```bash
mondo column list --board 5094861043 -o json
```

```json
[
  {"id": "name",          "title": "Name",         "type": "name"},
  {"id": "e2e_status",    "title": "Status",       "type": "status"},
  {"id": "e2e_person",    "title": "Owner",        "type": "people"},
  {"id": "e2e_date",      "title": "Due Date",     "type": "date"},
  {"id": "e2e_numbers",   "title": "Story Points", "type": "numbers"},
  {"id": "e2e_text",      "title": "Owner Email",  "type": "text"},
  {"id": "e2e_long_text", "title": "Description",  "type": "long_text"},
  {"id": "e2e_doc",       "title": "Spec Doc",     "type": "doc"}
]
```

*Gotcha:* `id` is the column key you'll use for `column set --column <id>`. The first column is always `name` (item title) and is non-deletable. The `people` type aliases to `person` in some response paths — match on `type in ('people', 'person')` if you're filtering.

*Note:* `column list` strips `settings_str` from each row (it's noisy). When you need the full metadata for a single column — e.g. enumerate dropdown options or read a `board_relation`'s target board id — use `column get-meta` instead (next section).

## Get metadata for a single column

```bash
mondo column get-meta --board 5094861043 --column e2e_status -o json
```

```json
{
  "id": "e2e_status",
  "title": "Status",
  "type": "status",
  "archived": false,
  "settings_str": "{\"labels\":{\"0\":\"Working on it\",\"1\":\"Done\",\"2\":\"Stuck\"}}"
}
```

*Gotcha:* `column get-meta` is sugar over `column list` narrowed to one column, with `settings_str` preserved (the whole reason this command exists). For dropdown/status columns prefer `mondo column labels --board X --column COL` which parses the labels for you.

```bash
# Just the settings_str payload, parsed downstream:
mondo column get-meta --board 5094861043 --column e2e_status -q settings_str -o none

# Project to a smaller shape:
mondo column get-meta --board 5094861043 --column e2e_status --fields id,title,type
```

## Create a typed column with a stable id

```bash
mondo column create --board 5094861043 \
  --title "Status" --type status --id e2e_status

mondo column create --board 5094861043 \
  --title "Description" --type long_text --id e2e_long_text
```

```json
{"id": "e2e_status", "title": "Status", "type": "status"}
```

### Seed initial labels (status / dropdown)

```bash
mondo column create --board 5094861043 \
  --title "Stage" --type status --labels "New,In Review,Live"

mondo column create --board 5094861043 \
  --title "Stack" --type dropdown --labels "Node/Express,Python/FastAPI"
```

*Gotcha:* `--labels` builds the right per-type `--defaults` payload for you (status uses an index→name object, dropdown an array of `{id,name}` under `settings`). It only applies to `status`/`dropdown` and is mutually exclusive with `--defaults`.

*Gotcha:* `--id` sets a **stable, human-readable column id** that survives renames — use it whenever you'll reference the column from scripts. Without it monday auto-assigns `text_xyz123`. Common types: `status`, `people`, `date`, `timeline`, `numbers`, `text`, `long_text`, `doc`, `dropdown`, `checkbox`, `country`, `email`, `phone`, `link`, `rating`, `tags`, `file`, `world_clock`, `board_relation`. See `mondo help codecs` for value-format hints per type.

## Read a column value (single item)

```bash
mondo column get --item 9876543210 --column e2e_status -o json
mondo column get --item 9876543210 --column e2e_long_text -o json
```

```json
"Done"
```

```json
"Initial spec for login + 2FA."
```

*Gotcha:* `column get` returns the **rendered text value** (a JSON string), not the typed/JSON column-value object. For raw monday column-value JSON, use `mondo item get --id <id>` and inspect `column_values[]`.

## Write a column value

```bash
# Status: pass the label text — codec resolves to monday's index value.
mondo column set --item 9876543210 --column e2e_status --value Done

# Numbers, text, long_text: literal value.
mondo column set --item 9876543210 --column e2e_numbers   --value 13
mondo column set --item 9876543210 --column e2e_text      --value hello@example.com
mondo column set --item 9876543210 --column e2e_long_text --value "Initial spec for login + 2FA."

# Date: ISO-8601 (YYYY-MM-DD).
mondo column set --item 9876543210 --column e2e_date --value 2026-06-30

# People: comma-separated user/team ids.
mondo column set --item 9876543210 --column e2e_person --value 12345,67890

# Dry-run any of the above to preview the GraphQL payload:
mondo column set --item 9876543210 --column e2e_status --value Done --dry-run
```

```json
{"id": "9876543210", "name": "Refactor auth middleware", "column_values": [{"id": "e2e_status", "text": "Done"}]}
```

*Gotcha:* the `--value` syntax goes through monday's per-type codec (see `mondo help codecs`). For complex types (timeline, board_relation, dropdown with multiple labels) the codec may need JSON instead of a label — `mondo column set --help` shows examples per type. When in doubt, run with `--dry-run` first to inspect the payload.

*Gotcha:* the `name` "column" (the item's title in monday's UI) is **not settable** via `change_column_value` — the mutation `column set` sends (including `--raw`). Rename items with `mondo item rename <item-id> --board <board-id> --name "<new name>"` instead (the error message points there too).

*Gotcha:* quote any `--value` (or `--column k=v`) containing shell metacharacters — `&`, spaces, parentheses. An unquoted `--column status=Accounts_&_Rights` makes zsh fork at the `&` and fail with `command not found`.

## Bulk-set a column across many items (`--batch`)

`column set --batch <path|->` sets values on many items in one shot, fanning each chunk into a single aliased GraphQL document (N rows = one HTTP call). It **requires `--board`** (board columns are fetched once instead of one context lookup per item) and is mutually exclusive with `--item`/`--value`/`--from-file`/`--from-stdin`.

Rows are `{item, value}` or `{item, column, value}`; a top-level `--column` supplies the default column for rows that omit one:

```bash
# Rows via stdin ('-'), default column supplied on the flag.
echo '[
  {"item": 9876543210, "value": "Done"},
  {"item": 9876543211, "value": "Working on it"},
  {"item": 9876543212, "column": "e2e_numbers", "value": 42}
]' | mondo column set --board 5094861043 --column e2e_status --batch - --chunk-size 10 -o json
```

```json
{
  "summary": {"requested": 3, "updated": 2, "failed": 1},
  "results": [
    {"ok": true,  "row_index": 0, "item": 9876543210, "column": "e2e_status"},
    {"ok": true,  "row_index": 1, "item": 9876543211, "column": "e2e_status"},
    {"ok": false, "row_index": 2, "item": 9876543212, "column": "e2e_numbers", "error": "..."}
  ]
}
```

- **Exit 1 on any per-row failure** (the envelope is still emitted — inspect `results[].ok` and retry the failures). A mid-batch HTTP error marks the failing + not-yet-attempted rows failed and still returns the partial envelope.
- `--dry-run` prints the resolved GraphQL document per chunk without sending. Tags-by-name can't be minted in `--dry-run` — pass tag **ids** there.
- The `name` column is rejected (rename items with `mondo item rename`), same as single-item mode.
- Clear-shaped values (`""`, `{}`, `[]`, `null`, `{"labels":[]}`) fail codec validation and the error points you at `mondo column clear`.

## Clear a column value

Don't guess empty payloads through `column set` (`--value ""` or `'{"labels":[]}'` fails codec validation, e.g. "unknown dropdown label"). `column clear` sends the correct empty payload for the column's type:

```bash
mondo column clear --item 9876543210 --column e2e_dropdown -y
```

## Read-only columns: mirror, formula, and friends

`mirror`, `formula`, `auto_number`, `creation_log`, `time_tracking`, … cannot be **written** (a `column set` attempt exits 5). But they now **read** correctly: typed reads render the computed `display_value` natively, so no graphql escape is needed.

- `column get --item <id> --column <mirror|formula|board_relation|dependency>` renders the `display_value`.
- `item list`/`item get -o json` carry `display_value` on those column values (and `linked_item_ids` for `board_relation`/`dependency`).
- Exports (`export board`) fall back to `display_value` when `text` is null.

So the old inline-fragment escape (`... on MirrorValue { display_value }` via `mondo graphql`) is **no longer necessary** for these reads — reach for it only if you need a raw field the typed selection doesn't expose.

## Multi-column writes on `item create`

Repeat `--column k=v` to set multiple columns at item creation time:

```bash
mondo item create --board 5094861043 --group backlog \
  --name "Refactor auth middleware" \
  --column e2e_status=Done \
  --column e2e_numbers=8 \
  --column "e2e_text=auth@example.com" \
  --column "e2e_long_text=Strip session token storage."
```

*Gotcha:* `--column k=v` uses the same codec layer as `column set` — same value formats apply. Quote values with spaces.

## monday quirks: board automations can overwrite `people` columns on create

A board may carry an **automation/recipe** like *"when an item is created, set <people column> to the creator"* (common on intake boards for a "Submitted by" or "Requester" column). When such a recipe exists, monday runs it **after** your `item create` mutation commits, so a value you passed via `--column <col>=<user_id>` is silently replaced with the **API caller's identity** (the user whose token mondo is using) — not an error, just a quiet overwrite.

This is **board-specific automation behaviour, not a `create_item` API quirk**: a plain `people` column with no recipe obeys the value you pass, and the recipe isn't visible through the public API. If a people column won't keep the value you set at create time:

```bash
# Workaround: create first, then set the column in a second step (runs after the recipe).
ITEM=$(mondo item create --board 5094861043 --name "New ticket" -q id -o none)
mondo column set --item "$ITEM" --column submitted_by --value 12345
```

Note this is distinct from the `creation_log` column type, which auto-records the creator by design and **rejects** any write (mondo's read-only codec blocks it; monday errors on raw attempts) — it never silently overwrites a passed value.

## `board_relation` / `dependency`: three accepted input shapes

For columns that take a list of item IDs (`board_relation`, `dependency`), the codec accepts any of:

```bash
# Single integer
mondo column set --item 987 --column related --value 12345

# CSV of integers
mondo column set --item 987 --column related --value '12345,67890'

# GraphQL-native JSON object — useful when you've copied a value from a monday API response
mondo column set --item 987 --column related --value '{"item_ids":[12345,67890]}'
```

All three produce the same payload (`{"item_ids":[...]}`). The JSON form is validated strictly: wrong top-level keys, non-list `item_ids`, or non-int IDs are rejected with a recovery-oriented error message that lists every accepted shape.

## Delete a column

```bash
mondo column delete --board 5094861043 --column e2e_long_text
```

*Gotcha:* deletion is **immediate** (no soft-archive) and irreversible. There's no `--hard` flag — `column delete` is always hard. Confirm-or-abort applies; pass `--yes` for non-interactive.

## Doc columns

The `doc` column type stores a pointer to a workdoc. Setting / appending / clearing doc columns has its own command surface (`mondo column doc set|get|append|clear`) — see `references/docs.md`.
