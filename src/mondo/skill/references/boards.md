# Boards

CRUD + duplicate + move on monday.com boards. Boards live in a workspace, optionally inside a folder, and contain groups + columns + items.

## Get a board by id

```bash
mondo board get --id 5094861043 -o json
mondo board get --id 5094861043 --with-url     # include /boards/<id> URL in output
```

```json
{
  "id": "5094861043",
  "name": "E2E PM Board",
  "workspace_id": "592446",
  "folder_id": "8612345",
  "state": "active",
  "url": "https://acct.monday.com/boards/5094861043"
}
```

*Gotcha:* if the id is a workdoc rather than a board, this command warns and points you at `mondo doc get --object-id <id>`. See `references/docs.md` and `mondo help boards-vs-docs`.

## List boards — all workspaces or scoped

`--workspace` is **optional**. Omitting it returns boards across **all workspaces** the authenticated user can see. Pass it (repeatably) to restrict.

```bash
mondo board list -o json                                           # all active boards, every workspace
mondo board list --name-contains "bonsy" -o json                  # cross-workspace name search
mondo board list --name-fuzzy "bonsi" --fuzzy-score -o json       # cross-workspace fuzzy search
mondo board list --workspace 592446 -o json                        # active boards in one workspace
mondo board list --workspace 592446 --state all --no-cache -o json # include archived; bypass cache
mondo board list --workspace 592446 --workspace 699169 -o json     # multiple workspaces
```

```json
[
  {"id": "5094861043", "name": "E2E PM Board", "state": "active"},
  {"id": "5094861099", "name": "Marketing", "state": "active"}
]
```

*Gotcha:* default omits archived boards. `--no-cache` bypasses the local cache when you need fresh state right after a write; otherwise leave the cache on (8h TTL for boards). Name filters (`--name-contains`, `--name-matches`, `--name-fuzzy`) are client-side and work with or without `--workspace`.

## Create a board

```bash
mondo board create \
  --workspace 592446 --folder 8612345 \
  --name "E2E PM Board abc12345" \
  --kind private \
  --empty
```

```json
{"id": "5094861043", "name": "E2E PM Board abc12345", "workspace_id": "592446", "folder_id": "8612345"}
```

*Gotcha:* `--empty` creates a fresh board with **no** template columns/items. Drop it to use monday's default template (Item / Subitems / People / Status / Date columns auto-added). `--kind` is `public | private | share`. `--folder` is optional but typical.

## Duplicate a board

Three modes:

```bash
# Structure only — columns + groups, zero items.
mondo board duplicate 5094861043 \
  --type duplicate_board_with_structure \
  --name "Dup Structure" \
  --workspace 592446 --folder 8612345

# Structure + items, no updates.
mondo board duplicate 5094861043 \
  --type duplicate_board_with_pulses \
  --name "Dup Pulses" \
  --workspace 592446 --folder 8612345 \
  --wait

# Full clone — structure + items + updates.
mondo board duplicate 5094861043 \
  --type duplicate_board_with_pulses_and_updates \
  --name "Dup Full" \
  --workspace 592446 --folder 8612345 \
  --wait
```

```json
{"board": {"id": "5094862099", "name": "Dup Pulses", "state": "active"}}
```

*Gotcha:* the response wraps the new board in a `board` key (`{"board": {"id": ...}}`), not a flat `{"id": ...}`. Plan your JMESPath accordingly: `-q board.id`. Without `--wait`, items may take seconds to appear — poll `mondo item list --board <new_id>` until the count is right. See `mondo help duplicate-and-customize` for the rename-after-clone pattern.

## Move a board between folders

```bash
mondo board move 5094862099 --folder 8612346
```

```json
{"id": "5094862099", "folder_id": "8612346"}
```

*Gotcha:* the move is async — `mondo board get --id <id>` may briefly still show the old `folder_id`. Re-poll if you need to gate on it.

## Archive vs hard-delete a board

```bash
mondo board delete --id 5094862099            # soft-archive (reversible from the UI)
mondo board delete --id 5094862099 --hard     # hard-delete (irreversible)
```

*Gotcha:* unsuffixed `delete` archives — the board is gone from the UI but retrievable from the trash. `--hard` deletes for real. Most automation paths want `--hard`. Pass `--yes` to skip the confirm prompt in non-interactive contexts; without it the command exits 1 with a "confirmation required" hint on closed stdin.

## Resolve a /boards/&lt;id&gt; URL

A URL like `https://<acct>.monday.com/boards/9876543210` may point to a board **or** to a workdoc that lives at the same path shape. Just try `board get` — if it's a doc, the CLI tells you:

```bash
mondo board get --id 9876543210 -o json
# stderr: not a board: id 9876543210 is a workdoc. Try `mondo doc get --object-id 9876543210`.
# exit 6
```

Then route to `mondo doc get --object-id <id>`. See `references/docs.md`.
