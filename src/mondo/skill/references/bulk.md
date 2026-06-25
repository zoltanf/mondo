# Bulk operations

Two surfaces:

- **`--batch <file.json>`** on per-resource commands (`item create`, `column set`, …): one HTTP round-trip, per-row envelope, partial-failure semantics.
- **`mondo export board` / `mondo import board`**: full-board export in CSV / TSV / JSON / XLSX / Markdown / HTML / PDF (all rendered client-side — monday has no native board-export endpoint). CSV/XLSX/JSON round-trip back via `import board`.

See `mondo help batch-operations` for the canonical prose deep-dive.

## Bulk-create items from JSON

Write rows to a JSON file (a list of dicts), one per item:

```json
[
  {"name": "E2E Batch #0", "group_id": "topics"},
  {"name": "E2E Batch #1", "group_id": "topics", "column_e2e_status": "Done"},
  {"name": "E2E Batch #2", "group_id": "topics"}
]
```

Then:

```bash
mondo item create --board 5094861043 --batch ./batch_ok.json -o json
```

```json
{
  "summary": {"requested": 3, "created": 3, "failed": 0},
  "results": [
    {"ok": true, "row_index": 0, "id": 9876543210, "name": "E2E Batch #0"},
    {"ok": true, "row_index": 1, "id": 9876543211, "name": "E2E Batch #1"},
    {"ok": true, "row_index": 2, "id": 9876543212, "name": "E2E Batch #2"}
  ]
}
```

*Gotcha:* exit `0` on full success, exit `1` on **any** per-row failure (still emits the envelope on stdout). Always inspect `results[].ok` to find failures — don't rely solely on the exit code. Column keys in the row dict use the form `column_<column_id>` (e.g. `column_e2e_status`).

## Partial-failure envelope

```json
{
  "summary": {"requested": 2, "created": 1, "failed": 1},
  "results": [
    {"ok": true,  "row_index": 0, "id": 9876543210, "name": "E2E BatchOK"},
    {"ok": false, "row_index": 1, "error": "group not found: definitely_not_a_real_group"}
  ]
}
```

```text
exit 1
```

*Gotcha:* the envelope is on **stdout**, not stderr — the JSON error envelope is only used for command-level failures (auth, validation, not-found). Per-row failures are part of the normal data response. Re-run only failed rows by filtering `results[?ok==false]`.

## Export a board

Formats: `csv | tsv | json | xlsx | md | html | pdf`. Stdout for csv/tsv/json/md/html; `--out` **required** for xlsx and pdf (exit 2 otherwise).

```bash
# JSON to stdout:
mondo export board 5094861043 --format json -o json

# CSV to a file:
mondo export board 5094861043 --format csv --out ./pm_export.csv

# XLSX (Excel) — bold/frozen header, autofilter, autosized cols; subitems on a 2nd sheet:
mondo export board 5094861043 --format xlsx --out ./pm_export.xlsx --include-subitems

# Markdown — grouped by default (board title <h1> + one ## section per group):
mondo export board 5094861043 --format md --out ./pm_export.md

# Self-contained HTML (defaults to stdout; --out optional):
mondo export board 5094861043 --format html --out ./pm_export.html

# PDF via WeasyPrint (requires --out):
mondo export board 5094861043 --format pdf --out ./pm_export.pdf
```

### Grouped vs flat (md / html / pdf only)

These three "human" formats are **grouped by default**: a board-name `# Title` (best-effort fetch; falls back to `Board <id>`, never errors) followed by one `## <group title>` / `<h2>` section per group that contains items, each with its own table. Grouped table headers are `id, name, state` + the column titles — `group` becomes the section heading, not a column. Group order = first-seen (board order); empty groups are omitted, and two groups sharing a title render under one heading.

```bash
# Single flat table instead (headers: id, name, state, group + column titles):
mondo export board 5094861043 --format md --flat
```

`--flat` has **no effect** on csv/tsv/json/xlsx. `--include-subitems` always appends a trailing `## Subitems` / `<h2>Subitems</h2>` section, grouped or flat.

### Narrowing & projection (all formats)

```bash
# Server-side filter (repeatable, AND'ed; labels resolve to indices/ids):
mondo export board 5094861043 --format csv --filter status=Done --filter owner!=

# One group (sugar for --filter group=<id>):
mondo export board 5094861043 --format md --group topics

# Client-side column projection (by id OR title, case-insensitive; meta cols always kept):
mondo export board 5094861043 --format csv --columns status,date4
```

*Gotcha:* `--filter`/`--group` narrow **server-side** via the items query (cheap on big boards); malformed `--filter` syntax fails fast with exit 2 before the client opens. `--columns` is **client-side projection only** — it doesn't reduce GraphQL cost; an unmatched token is a usage error (exit 2). `id/name/state` (+ `group` in flat mode) are always emitted regardless of `--columns`. CSV flattens column values to strings using the **column title** as the header; the `group` field carries the group title (not the id), matching `column list`'s `title`.

## Import a board from CSV

```bash
# 1. Build a fresh board with matching columns:
mondo board create --workspace 592446 --name "Imported PM" --kind private --empty

mondo group create  --board <fresh_board_id> --name "Imported"
mondo column create --board <fresh_board_id> --title "Owner Email"  --type text      --id text_owner_email
mondo column create --board <fresh_board_id> --title "Story Points" --type numbers   --id numbers_story_points
mondo column create --board <fresh_board_id> --title "Description"  --type long_text --id long_text_description

# 2. Import. --group <id> sets the default group for every row.
#    --group-column points at a CSV header that doesn't exist (suppresses
#    per-row group lookup, since the export stores group *titles* not IDs).
mondo import board <fresh_board_id> \
  --from ./pm_export.csv \
  --group <fresh_group_id> \
  --group-column __nogroup__
```

```json
{
  "summary": {"requested": 5, "created": 5, "failed": 0},
  "results": [
    {"ok": true, "row_index": 0, "id": 9876544000, "name": "Design login flow"}
  ]
}
```

*Gotcha:* `mondo export board ... --format csv` writes group **titles** under the `group` column, but `mondo import board` expects group **IDs**. Two paths: (a) override with `--group-column __nogroup__` + `--group <id>` (everything goes to one group), or (b) preprocess the CSV to replace group titles with ids. Status/dropdown/people values are best-effort on import — text, numbers, long_text round-trip cleanly.

## CSV round-trip pattern

```bash
# Export → fresh board → import:
mondo export board 5094861043 --format csv --out /tmp/pm.csv
mondo board create --workspace 592446 --name "Round Trip" --empty
# (then column + group setup as above)
mondo import board <new_board_id> --from /tmp/pm.csv \
  --group <default_group_id> --group-column __nogroup__
```

*Gotcha:* the round-trip is **lossy** for typed columns whose values are labels (status, dropdown, people). For full fidelity, use JSON export + scripting around `item create` directly.

## JSON error envelope (server errors only)

For command-level errors (not partial-batch), mondo writes one JSON line to stderr when stdout isn't a TTY:

```bash
mondo item delete --id 1 --hard       # bogus id; monday rejects
```

```text
exit 6
```

```json
{"error": "Item not found", "code": "NotFoundError", "exit_code": 6, "request_id": "req_abc123"}
```

*Gotcha:* parse stderr line-by-line and look for `{"exit_code": ..., "error": ...}` — the runtime may emit other diagnostics (cache notices, debug lines) above it. Branch on exit code + the envelope's `code` field, never on stderr text. Fields:

| Field | When present |
| --- | --- |
| `error`, `code`, `exit_code` | always |
| `request_id` | server-side errors (4xx/5xx) |
| `retry_in_seconds` | rate / complexity errors (exit 4) |
| `suggestion` | flag typos (e.g. "did you mean `--board`?") |
