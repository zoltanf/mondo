# Output formatting

Every `mondo` command emits structured data to stdout. Three global flags
control how it's shaped and how it's serialized — all three live together
in the "Output / Query" panel of every `--help` page:

    --query, -q  JMESPATH      Project / filter the payload before formatting.
    --fields     KEY1,KEY2,... CSV-style shorthand projection (dotted paths OK).
    --output, -o FORMAT        Serialize as table | json | jsonc | yaml | tsv | csv | none.

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

## CSV-style field projection (`--fields`)

For the most common projection — "give me id, name, status" — `--fields`
is shorter than the equivalent `-q '[].{...}'` JMESPath. Dotted paths
walk nested dicts:

    # Project a list of dicts to a smaller shape
    mondo item list --board 42 --fields id,name,state

    # Dotted paths drill into nested objects
    mondo item list --board 42 --fields id,name,creator.name

    # Works on single-dict responses too
    mondo item get --id 987 --fields id,name,url --with-url

Pipeline order: `-q` runs first (envelope extraction), then `--fields`
(row-shape narrowing). Both compose freely. Reach for `-q` when you
need filtering / aggregation / re-shaping; reach for `--fields` when you
just want a smaller dict per row.

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
