# Workspaces and folders

A **workspace** is the top-level account container; **folders** organise boards within a workspace and can nest. Boards live in a workspace, optionally inside a folder.

## List / get workspaces

```bash
mondo workspace list -o json
mondo workspace get --id 592446 -o json
```

```json
[
  {"id": 592446, "name": "monday.com Playground", "kind": "open"},
  {"id": 600001, "name": "Marketing",            "kind": "closed"}
]
```

*Gotcha:* most read commands accept `--workspace <id>` directly, so you rarely need a separate `workspace get` step. Cache TTL is 24h; use `--no-cache` after fresh writes.

## Folder tree (preferred for nested layouts)

```bash
mondo folder tree --workspace 592446 --no-cache -o json
```

```json
[
  {
    "id": 8612345, "name": "E2E Tree Root",
    "sub_folders": [
      {"id": 8612346, "name": "Alpha", "sub_folders": [
        {"id": 8612347, "name": "Alpha.1", "sub_folders": []}
      ]},
      {"id": 8612348, "name": "Beta", "sub_folders": []}
    ]
  }
]
```

*Gotcha:* the tree nests via `sub_folders` (also `folders` in some response paths — tolerate both). Walk recursively to find a folder by name. The flat `mondo folder list --workspace <id>` doesn't show nesting.

## Create a folder

```bash
# Top-level folder:
mondo folder create --workspace 592446 --name "Q3 Initiatives"

# Nested under another folder:
mondo folder create \
  --workspace 592446 \
  --parent 8612345 \
  --name "Q3 — Auth"
```

```json
{"id": 8612346, "name": "Q3 — Auth", "parent_id": 8612345}
```

*Gotcha:* `--parent` is the parent folder's id. Confirm nesting with `mondo folder get --id <new>` — `parent_id` should match. Folders may be returned with the parent as a nested object (`{"parent": {"id": ...}}`); tolerate both shapes.

## Get a folder

```bash
mondo folder get --id 8612346 -o json
```

```json
{"id": 8612346, "name": "Q3 — Auth", "parent_id": 8612345}
```

## List folders in a workspace (flat)

```bash
mondo folder list --workspace 592446 --no-cache -o json
```

```json
[
  {"id": 8612345, "name": "E2E Tree Root", "parent_id": null},
  {"id": 8612346, "name": "Q3 — Auth",     "parent_id": 8612345}
]
```

*Gotcha:* `folder list` is flat — no nesting. Use `folder tree` when you need the hierarchy.

## Rename a folder

```bash
mondo folder update 8612346 --name "Q3 — Auth (renamed)"
```

```json
{"id": 8612346, "name": "Q3 — Auth (renamed)"}
```

*Gotcha:* `folder update` takes the folder id as a **positional argument**, not `--id`. Renames take a moment to propagate to listings; poll if asserting on `folder list`.

## Move a folder (or boards)

There's no `folder move` command for folders themselves — to relocate, recreate at the new parent and move the contained boards via `mondo board move --id <board> --folder <new>`. See `references/boards.md`.

## Delete a folder

```bash
mondo folder delete --id 8612346 --hard
mondo folder delete 8612346 --hard            # positional form also accepted
```

*Gotcha:* deleting a folder **archives** (or deletes — depends on workspace policy) every board inside it. The boards drop out of `board list --state active`; check `--state all` to see them. Plan for cascade: if you only want to remove the folder, move boards out first (`board move --id <board_id> --folder <other_id>`).
