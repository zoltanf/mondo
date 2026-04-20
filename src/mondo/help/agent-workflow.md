# Using mondo from an agent

Short guide for AI agents, CI scripts, and automation pipelines.

## Discover, don't guess

Three discovery mechanisms, all offline:

    mondo help                      # list available topics
    mondo help --dump-spec -o json  # full machine-readable contract
    mondo <group> --help            # terminal help for a subcommand tree

`--dump-spec` is the one you want if you're planning multiple calls. It
emits every command's flags, types, required-ness, enum choices, docstring,
and runnable examples as a single JSON tree. Ingest once; plan many.

## Shape of a well-formed invocation

    mondo [-o json] [-q JMESPATH] [--api-token $TOKEN] <group> <cmd> [flags]

Recommended defaults when driven by an agent:

- **Never set `-o json` explicitly** — when stdout isn't a TTY (the agent
  case), `mondo` picks JSON automatically. Setting it is harmless but
  redundant.
- **Prefer `MONDAY_API_TOKEN`** over `--api-token` — the flag lands in
  process args, where other users on the host may see it.
- **Use `--dry-run` first** when mutating from a new script. It prints the
  outgoing GraphQL without calling monday.
- **Branch on exit code, not stderr** — codes are stable; stderr text isn't.

## Common idioms

    # Get a single field as a scalar
    id=$(mondo me -q id -o none)

    # Loop the first N items on a board
    mondo item list --board 42 --max-items 100 -q '[].id' -o json

    # Preview a mutation before sending it
    mondo --dry-run item create --board 42 --name "Test" --column status=Done

    # Agent-driven retries: 4 is retryable, 7 is retryable, others aren't.
    if mondo item create ...; then
      :
    elif [ $? -eq 4 ]; then
      sleep 60 && retry
    fi

## Error handling

Every error emits to stderr and returns a specific exit code:

| Code | Meaning                        | Retry? |
|------|--------------------------------|--------|
| 2    | Usage                          | No     |
| 3    | Auth                           | No — fix token |
| 4    | Rate / complexity              | **Yes** with 60s backoff |
| 5    | Validation                     | No — fix the value |
| 6    | Not found                      | No — fix the ID |
| 7    | Network                        | Yes, exponential |

Full detail: `mondo help exit-codes`.

## The escape hatch

Anything `mondo` doesn't wrap, use `mondo graphql` — same auth, same
output formatting, same exit codes, no codec layer in between. See
`mondo help graphql`.

## What to read next

- `mondo help codecs` — how `--column K=V` values are parsed per column type.
- `mondo help output` — JMESPath projection, format selection.
- `mondo help complexity` — staying within monday's per-minute budget.
- `mondo help filters` — server-side filter syntax for list commands.
- `mondo help auth` — token resolution chain.
- `mondo help profiles` — multi-account configuration.
- `mondo help boards-vs-docs` — reading monday URLs, workdoc detection, and `--with-url`.
