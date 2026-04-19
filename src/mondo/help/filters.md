# Filters, sorting & pagination

`mondo item list` and related list commands support both server-side
filtering (via monday's `items_page` query) and client-side JMESPath
projection (via `-q`). Pick the right one for the job.

## Server-side — `--filter`

Cheaper (monday skips non-matching items before returning) and scales to
boards with tens of thousands of items.

    # Single equality
    mondo item list --board 42 --filter status=Done

    # Inequality
    mondo item list --board 42 --filter status!=Stuck

    # Multi-value (any-of)
    mondo item list --board 42 --filter status=Done,Working

    # Combine rules — all are AND'ed together
    mondo item list --board 42 \
        --filter status=Done \
        --filter owner=42

`--filter` accepts `COL=VAL` or `COL!=VAL`. Comma-separated values on the
right become `any_of` / `not_any_of` rules.

For richer predicates (OR, nested groups, per-column operators),
`mondo aggregate board` and `mondo item list` both accept a raw
`--filter '<json>'` with the full monday `QueryParams` shape.

## Sorting

    mondo item list --board 42 --order-by date4           # asc by default
    mondo item list --board 42 --order-by date4,desc

`--order-by` takes either `COL` or `COL,DIR` where `DIR` is `asc` or
`desc`.

## Pagination

monday caps each page at 500 items. `mondo` hides the cursor by default
and keeps paging until the server runs out or `--max-items` is reached.

    # Default: page size = max, keep going until done
    mondo item list --board 42

    # Small pages (useful with --debug to watch complexity drain per page)
    mondo item list --board 42 --limit 50

    # Cap the total items returned (approximate — cuts at page boundary)
    mondo item list --board 42 --max-items 500

## Client-side filtering (`-q`)

When the server has no matching filter operator (e.g. the `boards` query
has no name filter), use JMESPath:

    mondo graphql 'query { boards(limit:200) { id name } }' \
        -q "data.boards[?contains(name,'Pager')]" -o table

See also: `mondo help output` for JMESPath projection, `mondo help
complexity` for how filtering affects cost.
