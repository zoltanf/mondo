# Groups

Groups are the named sections of a board (e.g. *Backlog*, *In Progress*, *Done*). Items live inside groups. All group commands take `--board <id>`.

## List groups on a board

```bash
mondo group list --board 5094861043 -o json
```

```json
[
  {"id": "topics",   "title": "Backlog",     "position": "1.000"},
  {"id": "group_42", "title": "In Progress", "position": "2.000"},
  {"id": "group_43", "title": "Done",        "position": "3.000"}
]
```

*Gotcha:* the field is `title`, not `name` — even though `--name` is the flag you use to **set** it on create.

## Create a group

```bash
mondo group create --board 5094861043 --name "Q3 Goals"
```

```json
{"id": "new_group_124", "title": "Q3 Goals", "position": "4.000"}
```

*Gotcha:* the new group is appended to the end. To reorder, use `group update --attribute position`.

## Rename a group (selectors)

Three ways to pick the group to rename: by `--id`, by `--name-contains <substring>`, or by `--name-fuzzy <approximate>` (Levenshtein, default threshold 70).

```bash
# By id (always unambiguous):
mondo group rename --board 5094861043 --id group_42 --title "Doing Now"

# By substring; if multiple groups match, this exits 2 unless --first is added:
mondo group rename --board 5094861043 \
  --name-contains "Alpha" --title "Alpha (active)"

# Disambiguate with --first (picks lowest-position match):
mondo group rename --board 5094861043 \
  --name-contains "Alpha" --first --title "Alpha (active)"

# Fuzzy match — useful when the user typed a typo:
mondo group rename --board 5094861043 \
  --name-fuzzy "in progres" --title "In Progress (renamed)"
```

```json
{"id": "group_42", "title": "Doing Now"}
```

*Gotcha:* ambiguous `--name-contains` returns exit 2 (usage error), not 5. Always pair with `--first` when you intend "any matching group".

## Update other group attributes

```bash
# Change title (alias for `rename`):
mondo group update --board 5094861043 --id group_42 \
  --attribute title --value "New Title"

# Change color (monday's named palette: e.g. green, blue, red, …):
mondo group update --board 5094861043 --id group_42 \
  --attribute color --value green

# Reorder (lower number = closer to top):
mondo group update --board 5094861043 --id group_42 \
  --attribute position --value 0.5
```

*Gotcha:* `--attribute` accepts `title`, `color`, `position`. Unknown attributes exit 2. Selectors (`--id` / `--name-contains` / `--name-fuzzy` / `--first`) work here too.

## Delete (archive vs hard-delete) a group

```bash
mondo group delete --board 5094861043 --id group_42            # soft-archive
mondo group delete --board 5094861043 --id group_42 --hard     # hard-delete
```

*Gotcha:* deleting a group **also deletes its items**. If you only meant to clear the group label, move items out first (`item move`). Without `--yes` this prompts; with closed stdin it exits 1 with a "confirmation required" hint.
