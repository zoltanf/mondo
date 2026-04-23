---
name: mondo
description: Use when the user wants to do anything against monday.com via the `mondo` CLI — reading or writing workspaces, folders, boards, groups, items, subitems, columns, updates, docs, files, users, teams, webhooks, or when they paste a monday.com URL.
---

# mondo

`mondo` is a power-user CLI for the monday.com GraphQL API (az/gh/gam style).
Invoke via the `mondo` binary on PATH. Authenticate once with `mondo auth login`.

## Discover, don't guess

- `mondo --help` — top-level command groups.
- `mondo <group> [<cmd>] --help` — flags for any command.
- `mondo help` — list bundled prose topics.
- `mondo help --dump-spec -o json` — full machine-readable command tree. Prefer this over scraping `--help`.

## monday.com object model

- **workspace** holds **folders** and **boards**.
- **board** contains **groups** (sections) and **columns** (typed fields); groups contain **items** (rows).
- **item** has **subitems** and **column values**; column types include `status`, `date`, `people`, `numbers`, `dropdown`, `doc`, `board_relation`, …
- **update** = comment on an item. **doc** = workspace-level rich document (not the `doc` column).
- **user**, **team**, **tag**, **webhook**, **favorite**, **activity**, **validation** — each has its own `mondo <group>`.

URL hint: `/boards/<id>` may be a board **or** a workdoc — `mondo board get` warns when the id is a document and points you at `mondo doc get --object-id <id>`.

## Operating norms

- **Dry-run writes first:** every mutating command takes `--dry-run`.
- **Non-TTY auto-JSON:** don't set `-o json` in scripts; mondo detects it. Force with `-o json|yaml|tsv|csv`.
- **Project before formatting** with `-q JMESPATH`.
- **Server-side filters** (`--filter col=val`, repeatable, AND'ed) beat client-side filtering on large boards.
- **Stable exit codes:** 0 ok, 2 usage, 3 auth, 4 rate/complexity (retry after 60s), 5 validation, 6 not-found, 7 network.
- **Escape hatch:** `mondo graphql '<query>'` for anything no subcommand covers.
- Return clickable monday URLs to the user (use `--with-url` on get commands).
