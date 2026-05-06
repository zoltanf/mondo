# Files

Upload and download file assets attached to file columns or updates.

## Upload to a file column

```bash
mondo file upload \
  --file ./spec.pdf \
  --target item \
  --item 9876543210 \
  --column e2e_file
```

```json
{
  "assets": [{
    "id": 1234567,
    "name": "spec.pdf",
    "url": "https://files.monday.com/...",
    "file_size": 84321
  }]
}
```

*Gotcha:* the response shape varies by target — file-column uploads return an `assets[]` list; update uploads can return a nested `change_column_value` or `add_file_to_update` object. To extract the asset id robustly, walk: `assets[0].id`, then `change_column_value.id`, then `add_file_to_update.id`. The asset id is what `mondo file download --asset` accepts.

## Upload to an update

```bash
mondo file upload \
  --file ./screenshot.png \
  --target update \
  --update 4242424242
```

*Gotcha:* the update has to exist first. The asset is attached to that specific update; deleting the update detaches the asset.

## Download an asset by id

```bash
mondo file download --asset 1234567 --out ./downloaded.bin
```

```text
(no JSON; writes the file at --out)
```

*Gotcha:* `mondo file download` does **not** emit JSON to stdout — it writes the asset bytes to `--out` and exits 0 on success. Don't try to pipe its stdout. To check the download succeeded, test for the file's existence + size. If `--asset` is wrong/expired, exit 6 (not found).

## Find an asset id when you don't have it

```bash
# From a file-column read:
mondo column get --item 9876543210 --column e2e_file -o json
# (returns a JSON list of {asset_id, name, url, ...})

# From the item shape:
mondo item get --id 9876543210 -o json -q "column_values[?id=='e2e_file'].value"
```

*Gotcha:* the URL emitted in the column value is **time-limited** (signed) — refresh by re-reading the column rather than caching the URL.
