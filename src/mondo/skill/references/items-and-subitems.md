# Items and subitems

Items are rows on a board. Subitems are rows on a board's auto-generated subitems board, parented to one item. Same column primitives apply to both.

## Create an item

```bash
mondo item create --board 5094861043 --group backlog --name "Refactor auth middleware"

# Get the new item's monday URL back without a follow-up GET:
mondo item create --board 5094861043 --name "Fix CI" --with-url
```

```json
{"id": "9876543210", "name": "Refactor auth middleware", "board": {"id": "5094861043"}, "group": {"id": "backlog"}}
```

*Gotcha:* `--group <id>` is the group's id (e.g. `topics`, `group_42`), not its title. List groups first if you only know the title: `mondo group list --board <id>`.

*New flag:* `--with-url` (also available on `item get`, `board get`, etc.) appends the canonical `https://<tenant>.monday.com/boards/<bid>/pulses/<iid>` URL to the response — avoids the "create → get URL" two-step.

## Create an item with column values

```bash
mondo item create --board 5094861043 --group backlog \
  --name "Refactor auth middleware" \
  --column e2e_status=Working_on_it \
  --column e2e_numbers=8 \
  --column "e2e_long_text=Strip session token storage."
```

```json
{"id": "9876543211", "name": "Refactor auth middleware", "column_values": [{"id": "e2e_status", "text": "Working on it"}, {"id": "e2e_numbers", "text": "8"}]}
```

*Gotcha:* repeat `--column k=v` per column. Same codec layer as `column set` — see `references/columns.md` and `mondo help codecs` for value formats per type. Status labels with spaces: use underscore in shell or quote (`--column "e2e_status=Working on it"`).

## Get an item by id

```bash
mondo item get --id 9876543210 -o json
mondo item get --id 9876543210 --with-url
```

```json
{
  "id": "9876543210",
  "name": "Refactor auth middleware",
  "state": "active",
  "board": {"id": "5094861043", "name": "E2E PM Board"},
  "group": {"id": "backlog", "title": "Backlog"},
  "column_values": [
    {"id": "e2e_status",  "text": "Working on it"},
    {"id": "e2e_numbers", "text": "8"}
  ],
  "url": "https://acct.monday.com/boards/5094861043/pulses/9876543210"
}
```

*Gotcha:* `column_values[]` only has columns that have a non-default value. Empty columns are omitted. Use `mondo column get --item <id> --column <col_id>` if you need a specific empty-aware read.

## List items on a board

```bash
mondo item list --board 5094861043 -o json
mondo item list --board 5094861043 --filter status=Done -o json   # server-side filter
mondo item list --board 5094861043 --group backlog -o json        # first-class group shortcut
mondo item list --parent 9876543210 -o json                       # subitems of a parent
mondo item list --board 5094861043 --fields id,name -o json       # auto-drops column_values → ~3x cheaper
mondo item list --board 5094861043 --columns status,person        # only these column values, server-side
```

```json
[
  {"id": "9876543210", "name": "Refactor auth middleware", "group": {"id": "backlog"}},
  {"id": "9876543211", "name": "Implement OAuth callback", "group": {"id": "in_progress"}}
]
```

*Gotcha:* `--filter col=val` is server-side and **AND'ed** when repeated; far cheaper than client-side JMESPath on big boards. For text contains-style search, monday's API doesn't support it — list and filter client-side with `-q "[?contains(name, 'auth')]"`.

*Cost model:* on boards beyond a few hundred items the full `column_values` selection is ~**3x** the per-page complexity/wall time of the bare item fields (~2.9s vs ~8.7s per 500-item page on a 1.3k-item board). `--fields id,name` (any `--fields` set not reading `column_values`) auto-drops `column_values` from the GraphQL query — a `-q` never auto-slims (it can read fields inside predicates yet return whole rows), so use `-q` to shape and `--fields` to slim. `--columns col1,col2` narrows it server-side to just those columns (also on `item get`); unknown column ids are silently omitted by the API (no error). See `mondo help complexity`.

*Shortcuts (first-class flags, not aliases of `--filter`):*

- `--group <id>` — sugar over `--filter group=<id>`. Composes with `--filter`.
- `--parent <item-id>` — switches to the subitems query for that parent. When set, `--board` becomes optional. Equivalent to `mondo subitem list --parent <id>` (same shape).
- `--refresh-cache` / `--no-cache` — load-bearing on `item list --parent <id>` (per-parent `subitems/<id>.json` cache, 60s TTL — see below), on the per-item `item get` cache (`items/<id>.json`, 60s), **and** on board-scope `item list`: the bare `--board` (and `--board --group`) variants are served from a 60s `board_items/<board_id>.json` cache — a repeat listing inside a triage loop costs ~1s instead of ~23s on a 1.3k-item board. Filtered / ordered / `--columns` variants always fetch live. mondo writes to the board drop the cache in-process; cross-client writes ride the 60s TTL — `--refresh-cache` when in doubt.

## Find items by column value

```bash
mondo item find --board 5094861043 --column e2e_status --value Done -o json
mondo item find --board 5094861043 --column e2e_status --value 'Done,Working on it'  # any-of
mondo item find --board 5094861043 --column e2e_status --value Done -q 'length(@)' -o none
```

*Gotcha:* `mondo item find` is sugar over `item list --filter COL=VAL`, returns the same shape, and inherits the same codec dispatch (so `--value` accepts status labels, dates, etc.) plus the `mondo column labels` pointer on unknown labels.

## Wait for an async state change

```bash
# Wait up to 30s for at least one item to appear (e.g. after a board duplicate)
mondo item list --board 5094861043 \
  --poll-until 'length(@) > `0`' --poll-interval 2s --poll-timeout 30s

# Wait for a specific item to flip to Done
mondo item get --id 9876543210 \
  --poll-until 'column_values[?id==`e2e_status`].text | [0] == `Done`' \
  --poll-interval 2s --poll-timeout 60s
```

*Gotcha:* available on `item list`, `item get`, `board get`. Durations accept compact strings (`500ms`, `2s`, `5m`, `1h`). On timeout the command exits non-zero with `WaitTimeoutError` in the error envelope. Replaces hand-rolled `until/sleep` loops in bash.

## Move an item between groups

```bash
mondo item move --id 9876543210 --group done
```

*Gotcha:* moving to a group on a **different** board needs `--board <new_id>` as well; otherwise the group must already exist on the item's current board.

## Selectors and `--first`

Like groups, item-level selectors support `--id`, `--name`, `--name-contains`, `--name-fuzzy`. Ambiguous matches exit 2 unless you pass `--first`:

```bash
# Unambiguous — by id:
mondo column set --item 9876543210 --column e2e_status --value Done

# By exact name (still risky if multiple items share the name):
mondo item get --board 5094861043 --name "Ship v2 launch"

# By substring + --first if duplicates are possible:
mondo item get --board 5094861043 --name-contains "v2" --first
```

## Archive vs hard-delete an item

```bash
mondo item delete --id 9876543210            # soft-archive (recoverable from trash)
mondo item delete --id 9876543210 --hard     # hard-delete
```

*Gotcha:* same as boards/groups. `--hard` is what most automation wants. Bare `delete` is reversible but quietly clutters the recycle bin.

## Subitems — create

```bash
mondo subitem create --parent 9876543210 --name "Write callback unit tests"
```

```json
{"id": "9876543299", "name": "Write callback unit tests", "board": {"id": "5094869999"}}
```

*Gotcha:* the first subitem on an item triggers monday to create a **dedicated subitems board** (`board.id` in the response). All subsequent subitems on any item of the same parent board share that subitems board.

## Subitems — list

```bash
mondo subitem list --parent 9876543210 -o json
```

```json
[
  {"id": "9876543299", "name": "Write callback unit tests", "board": {"id": "5094869999"}},
  {"id": "9876543300", "name": "QA login regression",       "board": {"id": "5094869999"}}
]
```

## Subitems — column ops

Subitems use the **regular `column` commands**, but the column ids belong to the subitems board, not the parent item's board. Resolve the subitems board id first:

```bash
# 1. Get the subitems board id by listing one subitem.
mondo subitem list --parent 9876543210 -o json -q "[0].board.id"
# → "5094869999"

# 2. List columns on the subitems board (default has only `name`):
mondo column list --board 5094869999

# 3. Add a text column to the subitems board (one-time per board):
mondo column create --board 5094869999 --title "Notes" --type text --id e2e_sub_text

# 4. Set a value on a specific subitem (uses `column set --item <subitem_id>`):
mondo column set --item 9876543299 --column e2e_sub_text --value "polishing"
```

*Gotcha:* there is no `subitem column set` — you use `column set --item <subitem_id>`. Subitems boards typically start with **just** the `name` column; you'll usually add columns once per board, then write per subitem.

## Subitems — get / delete

```bash
mondo subitem get --id 9876543299 -o json
mondo subitem delete --id 9876543299 --hard
```

*Gotcha:* `subitem get` returns the same shape as `item get` (column_values, board, etc.). Hard-deleting the **parent item** cascades to its subitems — you don't need to delete each subitem when cleaning up a parent.
