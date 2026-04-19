# Exit codes

`mondo` uses narrow, stable exit codes so agents and shell scripts can branch
on failure mode without parsing stderr.

| Code | Meaning                                               |
|------|-------------------------------------------------------|
| 0    | success                                               |
| 1    | generic error (unexpected — open an issue if repeatable) |
| 2    | usage error (bad flags, missing required, mutually-exclusive flags) |
| 3    | auth error (no token, invalid token, expired session) |
| 4    | rate / complexity budget exhausted after retries      |
| 5    | validation error (bad column value, unknown column id, read-only column) |
| 6    | not found (board / item / user / doc ID doesn't exist) |
| 7    | network / transport error (DNS, TLS, monday reachable?) |

## What stderr carries

When stdout isn't a TTY, error messages on stderr are also JSON — one line,
shape `{"error": "...", "code": N}`. Agents can parse either stream.

## Retry guidance

| Code | Retryable?                                            |
|------|-------------------------------------------------------|
| 0    | —                                                     |
| 1    | no (investigate)                                      |
| 2    | no (fix the command)                                  |
| 3    | no (refresh auth)                                     |
| 4    | **yes, with backoff** — complexity resets every minute |
| 5    | no (fix the value)                                    |
| 6    | no (fix the ID)                                       |
| 7    | yes (with exponential backoff; cap at ~3 attempts)    |

## Complexity specifically

Exit 4 is the one you *want* to retry. monday's budget is per-minute per-token,
shared across every API consumer on that token. See
`mondo complexity status` for the live budget, or `--debug` for a per-call
drain log.

See also: `mondo help output`, `mondo help codecs`.
