# Batch operations and title-based selectors

Two related agent-usability primitives, both meant to collapse the
"look up id, then act on it" round-trips that dominate seed-and-customize
workflows after `board duplicate`.

## Title-based selectors on rename / update

These commands accept the same `--name-contains` / `--name-matches` /
`--name-fuzzy` filter family used by `board list`:

- `mondo group rename`
- `mondo group update`
- `mondo column rename`
- `mondo item rename`

Pick a target by id (canonical, fastest), or by client-side title match.
The match flags are mutually exclusive among themselves and against
`--id`.

```bash
# After `board duplicate`, group ids are unstable strings like
# `duplicate_of_objective_2__we_t`. Rename by current title instead.
mondo group rename --board $BOARD \
    --name-contains "Objective 2" \
    --title "Objective 2: We have launched..."

# Regex match.
mondo group update --board $BOARD \
    --name-matches '^Objective \d+:' \
    --attribute color --value green

# Fuzzy match (typo-tolerant).
mondo column rename --board $BOARD \
    --name-fuzzy "stataus" --title "Workflow"
```

When a filter matches more than one row, the command refuses to act and
exits 2 with a list of candidates:

```
error: 2 groups matched: 'Draft A', 'Draft B'.
Pass --first to pick the first one, or refine the filter.
```

Pass `--first` to auto-pick the lowest-position match (top-of-board).
Zero matches exits 6 (not found).

The filter path issues one extra read (`groups`/`columns` cached;
`items_page` always live) before the mutation. When a known id is on
hand, pass it directly to skip the lookup.

## `mondo item create --batch`

Bulk-create items from a JSON array. The CLI fans the chunk into a single
GraphQL document via aliasing (`m_0..m_{N-1}`), so 7 items lands in 1
HTTP call instead of 7. Default chunk size is 10; tune with
`--chunk-size N`.

Per-row schema:

```json
[
  {
    "name": "KR 1.1",
    "group_id": "topics",
    "columns": ["status=Working on it", "owner=42"],
    "create_labels": false,
    "position_relative_method": "after_at",
    "relative_to": 12345
  },
  {"name": "KR 1.2", "group_id": "topics"}
]
```

Only `name` is required. The rest mirror the single-row flag vocabulary
1:1 (`--column` -> `columns`, `--group` -> `group_id`, etc.) so an agent
can transcribe a working `mondo item create` invocation into a batch row
without re-mapping field names.

```bash
# From a file (default chunk size 10)
mondo item create --board $BOARD --batch items.json

# From stdin
echo '[{"name":"A"},{"name":"B"},{"name":"C"}]' \
  | mondo item create --board $BOARD --batch -

# Smaller chunks (debug or work around complexity limits)
mondo item create --board $BOARD --batch items.json --chunk-size 3

# Dry-run prints each chunk's resolved query+variables without sending
mondo --dry-run item create --board $BOARD --batch items.json
```

The result envelope mirrors `mondo import board`:

```json
{
  "summary": {"requested": 7, "created": 6, "failed": 1},
  "results": [
    {"ok": true, "row_index": 0, "name": "KR 1.1", "id": "12345", "data": {...}},
    ...
    {"ok": false, "row_index": 6, "name": "KR 1.7", "error": "..."}
  ]
}
```

Exit 0 when every row succeeds; exit 1 when any row failed (the envelope
is still emitted, so the caller can pick winners and retry the rest).

`--batch` is mutually exclusive with the single-row flags
(`--name`, `--group`, `--column`, `--position-*`, `--relative-to`). Move
those settings into the JSON rows.

## When to reach for what

- One known id, one mutation: pass `--id`. No filter, no batch.
- One mutation, target known by title only: `--name-contains` (or
  `--name-matches` for regex). Add `--first` if you knowingly accept
  any match.
- Many similar mutations in one go: `--batch` with a JSON array. Avoids
  N HTTP round-trips and gives you a single result envelope to triage.
