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

> **Common trap — `-q`/`--query` is the global JMESPath projection,
> not the GraphQL query.** If you type `mondo graphql --query 'query
> { … }'` (or `-q '…'`), Click consumes the GraphQL string as the
> JMESPath and leaves the positional empty. `mondo` detects this case
> and runs the value as the GraphQL document anyway (with a stderr
> note), but the JMESPath projection is disabled for that invocation —
> the value can't be both. Pass the query positionally to combine it
> with a projection: `mondo graphql 'query { … }' -q 'me'`.

## Output: unwrapped `data` by default

Like the typed subcommands, `mondo graphql` prints the **unwrapped `data`
object** — not the full `{data, errors, extensions}` envelope. So `-q`
and jq paths address the result directly, with no `.data` prefix:

    mondo graphql 'query { me { id name } }' -q 'me.name'
    mondo graphql 'query { boards { id } }' | jq '.boards[]'

A response that carries a GraphQL `errors` array fails loudly (non-zero
exit), just like a typed subcommand — it does not emit a misleading
`null`. Pass `--raw` to print the full envelope verbatim instead:

    mondo graphql 'query { me { id } }' --raw

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
- No dry-run — passing `--dry-run` is **rejected with exit 2**. The raw
  passthrough can't preview safely (mondo doesn't parse your query), so
  rather than silently send the mutation anyway, the flag is refused.
  Eyeball your query manually, then re-run without `--dry-run` — or use
  a typed subcommand when one wraps your operation.

All the *other* globals still apply: `--output`, `--query`, `--profile`,
`--api-token`, `--debug`.

## Exit codes map the same way

3 = auth, 4 = rate/complexity (if monday volunteers the error),
5 = validation (server rejected your shape), 6 = not found,
7 = network. See `mondo help exit-codes`.

See also: `mondo help codecs`, `mondo help output`.
