# Raw GraphQL passthrough

Most of what an agent needs is covered by typed subcommands (`mondo item
...`, `mondo column ...`, etc.) — those apply codec parsing, complexity
metering, structured output, and sensible defaults. Use `mondo graphql`
when you need to:

- Call a query or mutation `mondo` doesn't wrap yet.
- Reproduce an exact payload from a monday API example.
- Exercise a new monday API feature before `mondo` ships support.

## Three input forms

    # Inline string
    mondo graphql 'query { me { id name } }'

    # From file (note the `@` prefix)
    mondo graphql @query.graphql

    # From stdin (note the trailing `-`)
    cat mutation.graphql | mondo graphql -

## Variables

    mondo graphql 'query ($ids:[ID!]!){ items(ids:$ids){ id name } }' \
        --vars '{"ids":[1,2]}'

Variables are parsed as a JSON object and forwarded to monday verbatim.

## What `mondo graphql` does NOT do

Unlike the typed subcommands, `mondo graphql` is a **raw passthrough**:

- No complexity-field injection — what you type is what gets sent. If you
  want the budget measured, add `complexity { query before after }` to
  your query manually.
- No codec dispatch — column values must already be in monday's expected
  JSON shape.
- No pagination — cursor handling is your responsibility.
- No dry-run — `--dry-run` is a no-op here.

All the *other* globals still apply: `--output`, `--query`, `--profile`,
`--api-token`, `--debug`.

## Exit codes map the same way

3 = auth, 4 = rate/complexity (if monday volunteers the error),
5 = validation (server rejected your shape), 6 = not found,
7 = network. See `mondo help exit-codes`.

See also: `mondo help codecs`, `mondo help output`.
