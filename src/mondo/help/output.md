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
        -q "boards[?contains(name,'Pager')]" -o table

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

Pipeline order: `-q` runs first (payload projection), then `--fields`
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

## Errors and stderr

Errors stay on **stderr**: a human-readable `error:` line plus, for most
errors — those raised through the shared error path — in machine output
mode (`-o json|jsonc|yaml`, or no `-o` with a non-TTY stdout), a one-line
JSON envelope `{"error", "code", "exit_code", "request_id",
"retry_in_seconds", "suggestion"}`. A minority of ad-hoc usage errors
still emit only the human-readable line.

Two behaviors keep failures visible in pipelines:

- **Fatal errors mirror the JSON envelope to stdout** in machine mode when
  the command dies before writing anything to stdout. A pipeline that
  suppressed stderr still receives a parseable `{"error": ..., "exit_code": N}`
  instead of empty input. The mirror never corrupts a partial-success
  stream (it only fires when stdout is still empty), `-o none` keeps
  stdout silent, and exit codes are unchanged. Note this applies even to
  commands whose success output is not JSON (e.g. `doc get --format
  markdown` redirected to a file): if they fail before producing output, the JSON
  envelope lands on stdout.
- **Benign notices are suppressed when no human is watching**: the
  `cache: hit (...)` provenance line and the skill-freshness warning only
  appear when stderr is a TTY (or with `--verbose` / `MONDO_VERBOSE=1`;
  `--explain-cache` always wins). Non-interactive runs get a clean stderr
  that carries errors only.

Don't `2>/dev/null` a mondo call — errors and recovery hints live on
stderr. Use `2>&1` or leave stderr attached; branch on the exit code.

## Global flags are position-free

az/gh/gam-style: global flags work anywhere on the command line.

    mondo item list --board 42 -o table -q '[].id'
    mondo -o table -q '[].id' item list --board 42   # also valid

See also: `mondo help exit-codes`, `mondo help codecs`.
