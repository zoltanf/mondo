# Output formatting

Every `mondo` command emits structured data to stdout. Two global flags
control how it's shaped and how it's serialized.

    --query, -q  JMESPATH    Project / filter the payload before formatting.
    --output, -o FORMAT      Serialize as table | json | jsonc | yaml | tsv | csv | none.

## Defaults

- **TTY stdout**: `table` (human-readable).
- **Non-TTY stdout** (pipes, file redirects, agent subprocesses): `json`.

So `mondo item list --board 42 | jq ...` just works — no need to set `-o json`
explicitly in scripts.

## JMESPath projection

`--query` runs **before** the formatter. That means you can reshape the
payload into a table-friendly form and still get a rendered table:

    # Project a few fields as a table
    mondo item list --board 42 -q '[].{id:id,name:name,state:state}'

    # Count matching rows, print the scalar
    mondo item list --board 42 -q "length(@)" -o none

    # Filter client-side (server has no name filter on `boards`):
    mondo graphql 'query { boards(limit:200) { id name } }' \
        -q "data.boards[?contains(name,'Pager')]" -o table

## Format notes

- `table` — rich-rendered, TTY only. Dropped columns become `…`.
- `json` — compact, newline-terminated. Safe to pipe into `jq`.
- `jsonc` — pretty-printed with 2-space indent. For humans reading logs.
- `yaml` — ruamel.yaml round-trip safe. Preserves ordering.
- `tsv` / `csv` — flattens nested records using dotted paths. Header row first.
- `none` — prints the raw scalar when `--query` collapses the payload to one.

## Global flags are position-free

az/gh/gam-style: global flags work anywhere on the command line.

    mondo item list --board 42 -o table -q '[].id'
    mondo -o table -q '[].id' item list --board 42   # also valid

See also: `mondo help exit-codes`, `mondo help codecs`.
