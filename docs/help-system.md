# Help system — design notes

Post-Phase-3 addition. Because `mondo` ships as a standalone binary
(PyInstaller — see [plan.md §15](plan.md)), any help, examples, or agent
onboarding content must be **bundled inside the artifact**. The README is
not reachable from a running binary, so every piece of agent-facing context
has to live in the wheel/binary itself.

The help system is organized in three independent but coherent layers.

---

## Layer 1 — per-command runnable examples

Every leaf command renders an `Examples` block below its Typer flag table:

    $ mondo item create --help
    ...
    Examples

      # Minimal create in the default group
      $ mondo item create --board 1234567890 --name "Fix CI"

      # Codec-parsed columns (status / people / date / tags)
      $ mondo item create --board 1234567890 --name "Fix CI" \
          --column status=Working --column owner=42 ...

**Source of truth:** `src/mondo/cli/_examples.py` holds the full registry as
a `dict[str, list[Example]]` keyed by dotted command path (`"item create"`,
`"column set"`, `"graphql"`). `epilog_for(path)` formats examples for Typer
using Rich markup, with zero-width-space paragraphs (`\u200b`) to force
visible blank lines between example blocks.

**Wiring:** each `@app.command` decorator passes `epilog=epilog_for("<group>
<cmd>")`. The `scripts/wire_epilogs.py` one-shot script is idempotent and
safe to rerun when new commands are added; it also injects the `from
mondo.cli._examples import epilog_for` import when missing.

**Why a registry, not inline strings:** the same registry feeds Layer 3
(`--dump-spec`) without duplication. Tests enforce that every leaf command
(except the `help` meta-command itself) has at least one example, and that
every example's command string contains `"mondo "` so agents can copy-paste
them verbatim.

> New command groups (e.g. `mondo cache` from the phase-4 directory cache)
> and new flags (`--name-fuzzy`, `--no-cache`, `--refresh-cache` on the four
> `list` commands) are surfaced the same way — registered in `_examples.py`,
> visible in both `mondo help <path>` and `mondo help --dump-spec`.

---

## Layer 2 — `mondo help <topic>`

Prose that doesn't belong on a single command's help page (cross-cutting
concerns, concepts, onboarding flows) ships as markdown files under
`src/mondo/help/*.md`, exposed via `importlib.resources`. Nine topics at
launch:

| Topic             | What's inside                                           |
|-------------------|---------------------------------------------------------|
| `agent-workflow`  | Short onboarding for AI agents and CI pipelines         |
| `auth`            | Token resolution chain + `mondo auth login`/`logout`    |
| `codecs`          | `--column COL=VAL` parsing table for every column type  |
| `complexity`      | monday's per-minute budget, retry guidance, debug logs  |
| `exit-codes`      | Exit codes 0–7 with retry/retry-not guidance            |
| `filters`         | Server-side `--filter` + client-side JMESPath recipes   |
| `graphql`         | Using `mondo graphql` as the escape hatch               |
| `output`          | `--output` / `--query` formatting + projection          |
| `profiles`        | Multi-account `config.yaml` + env-var interpolation     |

Listing (`mondo help`) enumerates topics from the package resource dir so
adding a topic requires no code change — drop a `*.md` file in
`src/mondo/help/` and it appears automatically.

**Rendering:** Rich-formatted markdown on a TTY, raw markdown on a pipe so
agents can ingest it into their own corpus / renderer. Unknown topic exits
with code 6 (not found) and lists available topics.

---

## Layer 3 — `mondo help --dump-spec`

Emits the full command tree as one JSON blob. The contract for agents:

    {
      "cli": "mondo",
      "root": {
        "name": "mondo",
        "commands": [
          {
            "name": "item",
            "commands": [
              {
                "name": "create",
                "path": "mondo item create",
                "help": "Create a new item on a board.",
                "params": [
                  {"name":"board_id","required":true,"flags":["--board"],...},
                  ...
                ],
                "examples": [
                  {"description":"...","command":"mondo item create ..."},
                  ...
                ],
                "epilog": "[bold]Examples[/bold]\n..."
              }
            ]
          }
        ]
      },
      "exit_codes": {"0":"success","2":"usage error","3":"auth error",...},
      "output_formats": ["table","json","jsonc","yaml","tsv","csv","none"]
    }

An agent ingests this once and plans many invocations without parsing
terminal help text. Enum choices (`click.Choice`) surface as `"choices":
["before_at","after_at"]`, so an agent can validate its proposed flag
values locally.

**Why it's generated, not hand-maintained:** `_dump_spec()` walks the live
Click command tree via `typer.main.get_command(root)`, so every new
subcommand or flag automatically appears. Drift is impossible by
construction.

---

## Discovery

All three layers are surfaced from the root `mondo --help` / bare-command
output via a custom epilog that points at `mondo help`, `mondo help codecs`
(as the canonical example topic), `mondo help --dump-spec -o json`, and
`mondo help agent-workflow`. Nothing about discovery requires reading the
README.

---

## Tests

Contract locked in `tests/unit/test_cli_help.py`:

- **Topic listing** surfaces the required topics (`agent-workflow`, `auth`,
  `codecs`, `complexity`, `exit-codes`, `filters`, `graphql`, `output`,
  `profiles`).
- **Every required topic renders** and starts with an `# H1` heading.
- **Unknown topic** exits 6 and lists available topics.
- **Epilog registry** is non-empty for every registered path and contains
  `"mondo "` in every example command.
- **Spec dump** has the expected top-level shape, enumerates the canonical
  command groups, exposes required-ness and enum choices, and surfaces the
  registered examples by round-trip.
- **Every leaf command has at least one example** (guards against silent
  regressions when adding new commands).

679 tests total as of this writing.

---

## Adding a new command — checklist

When adding a new `@app.command(...)`:

1. Add examples to `src/mondo/cli/_examples.py` under the dotted path key
   (`"<group> <cmd>"`). Aim for 2–4 examples covering the common idioms.
2. Wire `epilog=epilog_for("<group> <cmd>")` on the decorator — either
   directly or by rerunning `scripts/wire_epilogs.py`.
3. If the command introduces a cross-cutting concept, add a topic markdown
   file under `src/mondo/help/`.
4. `test_every_leaf_command_has_examples` will fail until step 1 is done;
   that's the enforcement mechanism.
