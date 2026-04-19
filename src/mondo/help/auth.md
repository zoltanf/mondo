# Authentication

`mondo` talks to monday.com's GraphQL API with a per-account personal API
token. Four resolution sources, highest precedence first:

1. `--api-token "..."` — per-invocation flag. Avoid on shared shells; the
   token lands in your history.
2. `MONDAY_API_TOKEN` environment variable — fine for one-off sessions, CI
   secrets, and containerized agents.
3. OS keyring — stored via `mondo auth login`, read on every subsequent
   invocation. Uses macOS Keychain, Windows Credential Manager, or libsecret.
4. Profile file `~/.config/mondo/config.yaml` — supports `${ENV_VAR}`
   interpolation and multiple named profiles.

Get the token from your monday profile → **Developers → API Token**.

## Quick start

    # Simplest — put the token in the environment for one session:
    export MONDAY_API_TOKEN="eyJhbGci..."
    mondo auth status

    # Persistent — store in the OS keyring:
    mondo auth login

    # Switch between accounts — use named profiles in config.yaml:
    mondo --profile work item list --board 42

## Verify before you automate

Any agent-driven pipeline should run `mondo auth status` as its first call.
It's a cheap query that confirms the token resolved, which user owns it, and
what the current complexity budget looks like — so authentication and
rate-limit problems surface *before* you start issuing mutations.

Exit code 3 specifically means "auth failed" — no token, invalid token, or
the monday server rejected it. See `mondo help exit-codes`.

## Logout

    mondo auth logout     # removes the keyring entry for the active profile

Environment variables and the `--api-token` flag are unaffected — only the
keyring is cleared.
