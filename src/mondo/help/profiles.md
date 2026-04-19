# Profiles & configuration

Multiple monday accounts, different API versions, default board IDs per
team — `mondo` handles these through named profiles in
`~/.config/mondo/config.yaml` (or `$XDG_CONFIG_HOME/mondo/config.yaml`).

## Minimal config

    default_profile: personal
    api_version: "2026-01"

    profiles:
      personal:
        api_token_keyring: "mondo:personal"     # read from OS keyring
        default_board_id: 1234567890
        output: table

## Multi-account

    profiles:
      personal:
        api_token_keyring: "mondo:personal"

      work:
        api_token: ${WORK_MONDAY_TOKEN}          # read from env
        api_version: "2025-10"                   # profile-level override
        default_workspace_id: 42

Select a profile:

    mondo --profile work item list --board 77
    MONDO_PROFILE=work mondo item list --board 77

## What a profile can set

| Key                    | Purpose                                           |
|------------------------|---------------------------------------------------|
| `api_token`            | Literal token. Env interpolation via `${VAR}`.    |
| `api_token_keyring`    | Keyring entry name (recommended over `api_token`). |
| `api_version`          | monday API version (`YYYY-MM`).                   |
| `default_board_id`     | Fallback `--board` for commands that take one.    |
| `default_workspace_id` | Fallback `--workspace`.                           |
| `output`               | Default output format for this profile.           |

Flags always beat profile values; env vars beat profile `api_token` only
(not other keys).

## Where mondo looks for config

Resolution order:

1. `MONDO_CONFIG=/some/path.yaml` — explicit override (also used by tests).
2. `$XDG_CONFIG_HOME/mondo/config.yaml` if `$XDG_CONFIG_HOME` is set.
3. `~/.config/mondo/config.yaml`.

Missing config is fine — you'll operate with defaults and env-var auth.

## Debug mode

If resolution isn't behaving as you expect, `--debug` logs where every
setting came from:

    mondo --debug auth status
    # token source: keyring (profile=personal)
    # api_version: 2026-01 (source=profile.work)

See also: `mondo help auth`, `mondo help output`.
