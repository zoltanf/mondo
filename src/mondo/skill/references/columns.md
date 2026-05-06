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

## Delete a column

```bash
mondo column delete --board 5094861043 --column e2e_long_text
```

*Gotcha:* deletion is **immediate** (no soft-archive) and irreversible. There's no `--hard` flag — `column delete` is always hard. Confirm-or-abort applies; pass `--yes` for non-interactive.

## Doc columns

The `doc` column type stores a pointer to a workdoc. Setting / appending / clearing doc columns has its own command surface (`mondo column doc set|get|append|clear`) — see `references/docs.md`.
