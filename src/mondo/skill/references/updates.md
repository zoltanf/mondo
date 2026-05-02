# Updates

Updates are comments on items (the right-hand "Updates" panel in monday's UI). They support nested replies, edits, likes, and pins.

## Post an update on an item

```bash
mondo update create --item 9876543210 --body "Reviewed the spec — LGTM."
```

```json
{"id": "4242424242", "text_body": "Reviewed the spec — LGTM.", "creator": {"id": 12345}}
```

*Gotcha:* the response field that carries the body text varies — sometimes `text_body`, sometimes `body`. When parsing, fall back: `(u.get("text_body") or u.get("body") or "")`.

## Reply to an update

```bash
mondo update reply --parent 4242424242 --body "+1, will start tomorrow."
```

```json
{"id": "4242424299", "text_body": "+1, will start tomorrow.", "parent_id": "4242424242"}
```

*Gotcha:* `--parent` is the parent **update id**, not the item id. To list a thread you list updates on the item; replies appear nested in `replies[]` on the parent update.

## Edit an update body

```bash
mondo update edit 4242424299 --body "+1, starting tomorrow morning."
```

*Gotcha:* `update edit` takes the update id as a **positional argument**, not `--id`. Edits land within seconds; if you're asserting the new body, poll `update list --item <id>` until the old body is gone.

## List updates for an item

```bash
mondo update list --item 9876543210 -o json
```

```json
[
  {
    "id": "4242424242",
    "text_body": "Reviewed the spec — LGTM.",
    "creator": {"id": 12345},
    "replies": [
      {"id": "4242424299", "text_body": "+1, starting tomorrow morning."}
    ]
  }
]
```

*Gotcha:* `replies[]` is nested on the parent update, not flattened. To search for a body across the whole thread, walk `replies[]` per top-level update. Limits: monday paginates updates server-side; `--limit` controls page size.

## Pin / unpin

```bash
mondo update pin 4242424242
mondo update unpin 4242424242
```

*Gotcha:* pinning is per-item — only one update can be pinned to the top of an item's update panel at a time. Pinning a different update silently moves the pin.

## Like / unlike

```bash
mondo update like 4242424242
mondo update unlike 4242424242
```

*Gotcha:* the like is recorded against the **authenticated user**. `update list` exposes likes either as `likes[]` or `liked_by[]` depending on the field set; tolerate both when parsing.

## Delete an update

```bash
mondo update delete 4242424242
```

*Gotcha:* deletes are immediate (no soft-archive, no `--hard` flag). Deleting a parent update **also deletes its replies**. Confirms unless `--yes` is set.
