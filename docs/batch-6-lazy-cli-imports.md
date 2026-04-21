# Batch 6 — Lazy CLI Sub-App Imports

> **Status:** ready to implement. Blocks on writing a parity test (§7) before
> the lazy path can ship enabled-by-default. Start behind an opt-in env flag.

---

## 1. Context

Mondo is a Typer-based CLI at `/Users/zoltanf/Development/Mdy` (Python 3.14,
Typer 0.24.1, Click 8.3.2). The project just finished a 5-batch simplify pass
(v0.4.5 → 5 refactor commits, ≈900 lines removed). Batch 6 was explicitly
deferred from that pass because it has higher blast radius than the other
batches and needs its own parity test before shipping.

**The problem:** `src/mondo/cli/main.py` currently imports all 23 command
sub-apps eagerly at module load:

```python
from mondo.cli.activity import app as activity_app
from mondo.cli.aggregate import app as aggregate_app
from mondo.cli.auth import app as auth_app
...
from mondo.cli.workspace import app as workspace_app
```

Running `mondo --help` (or any subcommand) forces the interpreter to import
every sub-module plus their transitive deps (`httpx`, `openpyxl`,
`rapidfuzz`, etc.). Cold-import of `mondo.cli.main` measures **~600 ms**
on current hardware; the real `uv run mondo --help` is ~573 ms wall-clock.
Not the dominant CLI latency (network calls swamp it), but every invocation
pays this cost before doing any useful work.

**The goal:** import a sub-app only when its command is actually invoked.
`mondo board list` should import `mondo.cli.board` (and its deps) but not
`mondo.cli.export`, `mondo.cli.import_`, `mondo.cli.file`, or the 19 others.

---

## 2. Baseline & files to read

Run the existing verification suite first to confirm you're on a clean tree:

```bash
uv run pytest            # expect 927 passing
uv run mypy src/mondo    # expect "no issues found"
uv run ruff check        # expect 15 pre-existing warnings in cache/, scripts/, tests/
```

Read these before touching code:

| File | Why |
|---|---|
| `src/mondo/cli/main.py` | Where the eager imports live. |
| `src/mondo/cli/help.py` | `help_command` and `_dump_spec` walk the **entire** command tree; §3 explains why this matters. |
| `src/mondo/cli/_examples.py` | Large help-text registry; **intentional per the help-system design**, do NOT touch. |
| `src/mondo/cli/argv.py` | `reorder_argv` runs on every invocation; needs to recognize subcommand names without importing them. |
| `tests/unit/test_cli_help.py` | Imports `_list_topics`, `_read_topic` from `mondo.cli.help` — those symbols must stay importable. |
| Any `tests/unit/test_cli_*.py` | All use `from mondo.cli.main import app` + `CliRunner`; none import individual sub-apps directly. Confirms test blast radius is low. |

**Blast radius confirmation (already checked):** a repo-wide grep shows
only `main.py` does `from mondo.cli.<sub> import app`. Test files use the
root `app` exclusively. `src/mondo/__main__.py` imports only
`mondo.cli.main:main`.

---

## 3. The two hard blockers

Before you write code, internalize these two constraints:

### 3a. `help --dump-spec` walks the full tree

`cli/help.py::_dump_spec` calls `typer.main.get_command(root_app)` then
recursively traverses via `click.Group.list_commands` / `get_command`. Its
entire purpose is to emit the complete CLI schema as JSON for agents to
consume. If the tree is lazy, `dump-spec` **must force-load every node**
when invoked. Any lazy design has to route `list_commands()` through the
lazy registry so `dump-spec` triggers all imports.

### 3b. `reorder_argv` needs to know subcommand names

`cli/argv.py::reorder_argv` moves root-level global flags (like `--output`,
`--profile`) around so they work before or after the subcommand (`az`/`gh`
UX). It needs to know which tokens are subcommand names so it doesn't
accidentally reorder them. Today it can get the set of names trivially (the
root Typer app has them all mounted). After lazy loading, the subcommand
names must still be known **without importing the sub-modules** — so the
lazy registry (a dict of `{name: "module:attr"}`) must be the source of
truth and `reorder_argv` must consult it.

---

## 4. Recommended design

**A `LazyTyperGroup` that subclasses `typer.core.TyperGroup` and overrides
`get_command` + `list_commands`.**

```
                 ┌──────────────┐
                 │  typer.Typer │   ← root app, callback-only, no add_typer
                 └──────┬───────┘
                        │ typer.main.get_command()
                        ▼
             ┌──────────────────────┐
             │  TyperGroup (click)  │
             └──────┬───────────────┘
                    │ wrap with our subclass
                    ▼
             ┌──────────────────────┐
             │    LazyTyperGroup    │
             │  ┌────────────────┐  │
             │  │ _LAZY_REGISTRY │  │   {"board": ("mondo.cli.board", "app", "help…"), ...}
             │  └────────────────┘  │
             │  get_command(ctx,n)  │ ── on first miss: importlib.import_module(mod),
             │                      │                   add_typer(loaded, name=n),
             │                      │                   regenerate+cache subtree
             │  list_commands(ctx)  │ ── returns union of eagerly-mounted + registry keys
             └──────────────────────┘
```

### Why this and not a factory pattern

Alternatives considered and rejected:

- **Factory pattern (`build_app() -> typer.Typer` per module):** touches every
  sub-module, would require changing each `app = typer.Typer(...)` to a
  factory function, and tests that currently do `from mondo.cli.board import app`
  would need to change (they don't today, but it's still 23 modules of churn).
- **Monkeypatching `.registered_commands` post-hoc:** couples to Typer
  internals that aren't public API.
- **Importing on Click dispatch via `resolve_command`:** same class of hack,
  but `get_command` is the public Click hook and is subclass-friendly.

The `get_command` override is the idiomatic Click pattern (the Click docs
have a similar snippet). It's the smallest surface area, touches only
`main.py`, and preserves every existing contract: tests keep working, the
console-script entry point doesn't change, `dump-spec` still walks the tree,
`mondo --help` still lists subcommands.

### Sub-apps that must stay eager

Some commands are mounted directly on the root as single commands (not
sub-Typer groups). Currently these are:

- `me`, `account` → `mondo.cli.me`
- `graphql` → `mondo.cli.graphql`
- `help` → `mondo.cli.help`

Of these, `help` must stay eager because `help --dump-spec` imports
`mondo.cli.main:app` and walks the tree — if help itself is lazy,
`dump-spec` triggers its own import before the tree is ready. The
registry entry for `help` should be special-cased or mounted eagerly.

`me`/`account` and `graphql` can stay eager with no cost — their modules
are small and don't pull heavy transitive deps.

---

## 5. Implementation steps

### 5a. Create the registry + LazyTyperGroup

New module: `src/mondo/cli/_lazy.py`

```python
"""Lazy sub-app loading for the mondo CLI.

Gates on the MONDO_LAZY_CLI env var so the feature can roll out behind a
flag. When disabled, `register_sub_apps()` mounts everything eagerly (the
pre-batch-6 behavior).
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

import typer
from typer.core import TyperGroup

if TYPE_CHECKING:
    import click


@dataclass(frozen=True)
class _SubApp:
    name: str          # CLI subcommand name (e.g. "board")
    module: str        # "mondo.cli.board"
    attr: str          # "app" — the typer.Typer instance inside the module
    help: str          # one-line help text shown in `mondo --help`


_SUB_APPS: list[_SubApp] = [
    _SubApp("auth", "mondo.cli.auth", "app", "Authenticate against monday.com."),
    _SubApp("cache", "mondo.cli.cache", "app",
            "Inspect, refresh, and clear the local directory cache."),
    _SubApp("board", "mondo.cli.board", "app",
            "Create, read, update, delete monday boards."),
    _SubApp("item", "mondo.cli.item", "app",
            "Create, read, update, delete monday items."),
    _SubApp("subitem", "mondo.cli.subitem", "app",
            "Create, read, update, delete subitems."),
    _SubApp("update", "mondo.cli.update", "app",
            "Post, edit, like, pin, and delete item updates (comments)."),
    _SubApp("doc", "mondo.cli.doc", "app",
            "Workspace-level docs (distinct from the `doc` column)."),
    _SubApp("webhook", "mondo.cli.webhook", "app",
            "Manage monday webhook subscriptions."),
    _SubApp("file", "mondo.cli.file", "app",
            "Upload files to item columns/updates; download assets."),
    _SubApp("folder", "mondo.cli.folder", "app", "Manage workspace folders."),
    _SubApp("tag", "mondo.cli.tag", "app",
            "Read account-level tags; create-or-get for a board."),
    _SubApp("favorite", "mondo.cli.favorite", "app",
            "List the current user's favorites."),
    _SubApp("activity", "mondo.cli.activity", "app",
            "Read a board's activity logs."),
    _SubApp("notify", "mondo.cli.notify", "app", "Send monday notifications."),
    _SubApp("aggregate", "mondo.cli.aggregate", "app",
            "Run SUM/COUNT/AVG aggregations on a board."),
    _SubApp("validation", "mondo.cli.validation", "app",
            "Manage server-side validation rules."),
    _SubApp("group", "mondo.cli.group", "app", "Manage groups within a board."),
    _SubApp("column", "mondo.cli.column", "app",
            "Read and write monday column values."),
    _SubApp("workspace", "mondo.cli.workspace", "app",
            "Manage workspaces and their members."),
    _SubApp("user", "mondo.cli.user", "app",
            "List and manage users (roles, team membership, activation)."),
    _SubApp("team", "mondo.cli.team", "app", "Manage teams and their owners."),
    _SubApp("export", "mondo.cli.export", "app",
            "Export a board's data to CSV/JSON/XLSX/Markdown."),
    _SubApp("import", "mondo.cli.import_", "app",
            "Bulk-import items from CSV into a board."),
    _SubApp("complexity", "mondo.cli.complexity", "app",
            "Inspect monday's per-minute complexity budget."),
]


# Public: names that reorder_argv needs to recognize without importing.
SUB_APP_NAMES: frozenset[str] = frozenset(s.name for s in _SUB_APPS)


def is_lazy_enabled() -> bool:
    return os.environ.get("MONDO_LAZY_CLI", "").strip().lower() in {"1", "true", "yes", "on"}


def register_eager(app: typer.Typer) -> None:
    """Pre-batch-6 behavior: import every sub-app and mount it now."""
    for sub in _SUB_APPS:
        module = importlib.import_module(sub.module)
        app.add_typer(getattr(module, sub.attr), name=sub.name, help=sub.help)


class LazyTyperGroup(TyperGroup):
    """Click group that imports sub-apps on first command lookup.

    Overrides:
      - get_command: on miss against the already-mounted commands, check the
        lazy registry, import the module, convert its Typer to a TyperGroup,
        and cache the result on `self.commands`.
      - list_commands: union of mounted names and lazy registry names, so
        `mondo --help` and `mondo help --dump-spec` see the full tree.

    `force_load_all()` is called by `help --dump-spec` to materialize
    everything before walking.
    """

    _lazy_registry: dict[str, _SubApp]  # populated by install_on()

    def list_commands(self, ctx: "click.Context") -> list[str]:
        seen = set(super().list_commands(ctx))
        seen.update(self._lazy_registry.keys())
        return sorted(seen)

    def get_command(self, ctx: "click.Context", cmd_name: str) -> "click.Command | None":
        existing = super().get_command(ctx, cmd_name)
        if existing is not None:
            return existing
        sub = self._lazy_registry.get(cmd_name)
        if sub is None:
            return None
        module = importlib.import_module(sub.module)
        typer_app = getattr(module, sub.attr)
        click_cmd = typer.main.get_command(typer_app)
        click_cmd.name = sub.name
        # Match the eager path's help text.
        click_cmd.help = sub.help
        self.commands[cmd_name] = click_cmd
        return click_cmd

    def force_load_all(self, ctx: "click.Context") -> None:
        for name in list(self._lazy_registry):
            self.get_command(ctx, name)


def install_on(root_app: typer.Typer) -> "click.Command":
    """Build the root Click command with lazy loading enabled.

    Returns the click.Command ready to be invoked. Caller is responsible
    for stashing it somewhere the entry point can reach.
    """
    click_root = typer.main.get_command(root_app)
    assert isinstance(click_root, TyperGroup), (
        f"expected TyperGroup from root app, got {type(click_root).__name__}"
    )
    click_root.__class__ = LazyTyperGroup
    click_root._lazy_registry = {s.name: s for s in _SUB_APPS}
    return click_root
```

### 5b. Rewire `main.py`

Replace the 23 `from mondo.cli.<x> import app as <x>_app` imports and the
23 `app.add_typer(...)` calls with a single branch:

```python
# main.py — simplified

import sys
import typer

from mondo.cli._examples import epilog_for
from mondo.cli._lazy import is_lazy_enabled, register_eager, install_on
from mondo.cli.argv import reorder_argv
from mondo.cli.context import GlobalOpts
from mondo.cli.graphql import graphql_command  # keep eager — small
from mondo.cli.help import help_command        # keep eager — dump-spec driver
from mondo.cli.me import account_command, me_command  # keep eager
from mondo.logging_ import configure_logging
from mondo.version import __version__

# ... (OutputFormat enum, _ROOT_EPILOG unchanged) ...

app = typer.Typer(name="mondo", help="…", epilog=_ROOT_EPILOG, ...)

# Root-level single commands stay eager.
app.command(name="me", ...)(me_command)
app.command(name="account", ...)(account_command)
app.command(name="graphql", ...)(graphql_command)
app.command(name="help", ...)(help_command)

# @app.callback() unchanged.

if is_lazy_enabled():
    _click_root = install_on(app)
else:
    register_eager(app)
    _click_root = None  # Typer will build on first invoke


def main() -> None:
    args = reorder_argv(sys.argv[1:])
    if _click_root is not None:
        _click_root(args=args, standalone_mode=True)
    else:
        app(args=args)
```

**Important:** tests do `from mondo.cli.main import app` and invoke via
`CliRunner(app)`. `CliRunner` accepts either a Typer or a Click command, so
the test path continues to work **against the eager Typer `app`** when
`MONDO_LAZY_CLI` is unset. Tests that want to exercise the lazy path must
set the env var explicitly — see §7.

### 5c. Update `argv.py` to use the shared name registry

If `reorder_argv` currently inspects `app.registered_groups` or similar to
discover subcommand names, swap it for `from mondo.cli._lazy import SUB_APP_NAMES`
plus the hard-coded eager-command names (`me`, `account`, `graphql`, `help`).
Read `src/mondo/cli/argv.py` first — the exact change depends on what the
current impl does.

### 5d. Teach `help --dump-spec` to force-load

`cli/help.py::help_command` currently does:

```python
from mondo.cli.main import app as root_app
if dump_spec:
    opts.emit(_dump_spec(root_app))
```

`_dump_spec` calls `typer.main.get_command(root_app)` which produces a
fresh Click tree. In lazy mode that tree starts empty (except for eager
commands). Two options:

1. **Use the already-installed click_root.** Change `help.py` to import
   `_click_root` from `main.py`; if it's non-None (lazy mode),
   call `click_root.force_load_all(ctx)` before walking. Falls back to the
   current Typer-tree path when `_click_root is None`.

2. **Walk lazily.** Have `_walk()` check `isinstance(cmd, LazyTyperGroup)`
   and call `force_load_all` there.

Option 1 is cleaner — keeps laziness knowledge in `_lazy.py` and the main
plumbing, not scattered into the spec walker.

### 5e. Touch no other files

If you find yourself editing a `src/mondo/cli/<sub>.py` module for this
batch, stop. Batch 6 should not touch any leaf command module. The point
is that they stay identical and only main.py's wiring changes.

---

## 6. Rollback signals

Each of these means the batch is wrong — **stop, don't force a fix, revert
and reconsider:**

| Symptom | What's broken |
|---|---|
| `mondo help --dump-spec -o json` emits a tree with fewer commands than the eager path | `list_commands` override missing registry keys, or `force_load_all` not called. |
| Any `tests/unit/test_cli_*.py` fails with "No such command 'board'" (etc.) | Eager path regressed — the `is_lazy_enabled()` branch isn't running `register_eager`. |
| `mondo board list --help` says "No such command 'list'" | Lazy import succeeded but the cached `click_cmd` isn't itself a group (help text of the Typer app wasn't preserved). Check `click_cmd.name` / `.help` assignment. |
| `mondo --help` column doesn't show sub-apps when lazy is on | `list_commands` override not reached (user subclass not installed correctly via `__class__` swap). |
| Test suite passes but `uv run mondo` has a Python `ModuleNotFoundError` at runtime | The `_SUB_APPS` registry has a typo in a `module` path. |
| `MONDO_LAZY_CLI=1 mondo board list ...` is noticeably slower than the eager path on a warm cache | Unexpected — investigate, don't ship. The whole point of lazy loading is that the imported path is at most equal to eager. |

---

## 7. Parity test (SHIP-BLOCKING — write this first)

**Do not merge Batch 6 without this test.** The whole safety case rests on
"lazy and eager modes produce the same command tree and the same behavior."
That claim has to be mechanically verified, not assumed.

Create `tests/unit/test_cli_lazy_parity.py`:

```python
"""Parity between eager CLI and MONDO_LAZY_CLI=1 CLI.

The lazy loader is a structural optimization — user-visible output,
command tree, and exit codes must be identical across the two modes.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner


def _reload_main(monkeypatch: pytest.MonkeyPatch, *, lazy: bool) -> object:
    """Reload mondo.cli.main with the requested mode and return its module."""
    if lazy:
        monkeypatch.setenv("MONDO_LAZY_CLI", "1")
    else:
        monkeypatch.delenv("MONDO_LAZY_CLI", raising=False)
    # Drop any cached mondo.cli.* modules so the wiring re-runs.
    for name in list(sys.modules):
        if name.startswith("mondo.cli"):
            del sys.modules[name]
    import mondo.cli.main as main_mod
    importlib.reload(main_mod)
    return main_mod


def _dump_spec(main_mod: object) -> dict:
    """Drive `mondo help --dump-spec -o json` via CliRunner, return parsed."""
    runner = CliRunner()
    result = runner.invoke(
        main_mod.app, ["help", "--dump-spec", "-o", "json"], catch_exceptions=False,
    )
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def _strip_volatile(tree: dict) -> dict:
    """Drop fields that might differ harmlessly between modes
    (e.g. object ids); keep everything semantic."""
    # If this ever needs real stripping, do it here — start empty.
    return tree


def test_dump_spec_tree_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """`help --dump-spec` must emit byte-identical trees in both modes."""
    eager_mod = _reload_main(monkeypatch, lazy=False)
    eager_spec = _dump_spec(eager_mod)

    lazy_mod = _reload_main(monkeypatch, lazy=True)
    lazy_spec = _dump_spec(lazy_mod)

    assert _strip_volatile(eager_spec) == _strip_volatile(lazy_spec)


def test_subcommand_help_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every sub-app's `--help` must render identically in both modes."""
    from mondo.cli._lazy import SUB_APP_NAMES

    eager_mod = _reload_main(monkeypatch, lazy=False)
    eager_runner = CliRunner()
    eager = {
        name: eager_runner.invoke(eager_mod.app, [name, "--help"]).stdout
        for name in SUB_APP_NAMES
    }

    lazy_mod = _reload_main(monkeypatch, lazy=True)
    lazy_runner = CliRunner()
    for name in SUB_APP_NAMES:
        result = lazy_runner.invoke(lazy_mod.app, [name, "--help"])
        assert result.stdout == eager[name], (
            f"help text for `{name}` diverges between eager and lazy modes"
        )


def test_lazy_does_not_preload_heavy_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Running `mondo --help` in lazy mode must not import most sub-app
    modules. Canaries: pick 3 sub-apps whose leaf modules weren't needed
    for `--help`."""
    # Run in a subprocess so we get a virgin interpreter.
    out = subprocess.run(
        [sys.executable, "-c",
         "import os, sys; "
         "os.environ['MONDO_LAZY_CLI']='1'; "
         "from mondo.cli.main import app; "
         "from typer.testing import CliRunner; "
         "CliRunner().invoke(app, ['--help']); "
         "print(','.join(sorted(n for n in sys.modules if n.startswith('mondo.cli.'))))"],
        capture_output=True, text=True, check=True,
    )
    loaded = set(out.stdout.strip().split(","))
    # These should NOT be imported by a plain --help in lazy mode.
    for canary in {"mondo.cli.export", "mondo.cli.import_", "mondo.cli.file"}:
        assert canary not in loaded, f"{canary} was loaded during --help"


def test_invoking_subcommand_loads_its_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lazy hook actually fires when a sub-app's subcommand is called."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import os, sys; "
         "os.environ['MONDO_LAZY_CLI']='1'; "
         "from mondo.cli.main import app; "
         "from typer.testing import CliRunner; "
         "CliRunner().invoke(app, ['board', '--help']); "
         "print('mondo.cli.board' in sys.modules)"],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "True"
```

Run it both ways to make sure it's real signal, not a tautology:

```bash
uv run pytest tests/unit/test_cli_lazy_parity.py -v
```

If the parity test fails while eager tests pass, **the bug is in the lazy
wiring, not the test.** Don't relax assertions to make it green.

---

## 8. Verification

Run after every meaningful change, and at the end before committing:

```bash
# Structural
uv run pytest                       # all 927 + new parity tests green
uv run mypy src/mondo               # clean
uv run ruff check                   # no NEW warnings (pre-existing 15 stay)

# Behavioral — eager path (the default)
uv run mondo --help > /tmp/eager-help.txt
uv run mondo help --dump-spec -o json > /tmp/eager-spec.json
uv run mondo board list --help > /tmp/eager-board-help.txt

# Behavioral — lazy path
MONDO_LAZY_CLI=1 uv run mondo --help > /tmp/lazy-help.txt
MONDO_LAZY_CLI=1 uv run mondo help --dump-spec -o json > /tmp/lazy-spec.json
MONDO_LAZY_CLI=1 uv run mondo board list --help > /tmp/lazy-board-help.txt

diff /tmp/eager-help.txt /tmp/lazy-help.txt
diff /tmp/eager-spec.json /tmp/lazy-spec.json
diff /tmp/eager-board-help.txt /tmp/lazy-board-help.txt
# All diffs empty.

# Timing (informational, not a test gate)
time uv run mondo --help
time MONDO_LAZY_CLI=1 uv run mondo --help
# Expect lazy to be ~equal or slightly faster on cold run.
```

---

## 9. Shipping strategy

Three-stage rollout. Do not skip stages.

### Stage 1 — land behind `MONDO_LAZY_CLI=1` (off by default)

- Implement §5.
- Write and land the parity test suite from §7.
- Default remains eager. Ship as a normal refactor release.
- Commit message: `feat(cli): opt-in lazy sub-app loading via MONDO_LAZY_CLI`.

### Stage 2 — flip the default

Only after at least one release cycle where the lazy path has been
exercised on real invocations (by the maintainer and/or any opt-in users).
Flip the default, rename the env var to `MONDO_EAGER_CLI=1` for the escape
hatch. Commit message: `feat(cli): lazy sub-app loading is now the default`.

### Stage 3 — remove the escape hatch

After the default-lazy release has been out long enough with no regressions,
remove `register_eager()` and the env-var branch entirely. Commit message:
`refactor(cli): drop eager sub-app loader (now only path)`.

---

## 10. Out-of-scope (leave alone)

- **`src/mondo/api/queries.py`** (1903 lines of GraphQL) — separate design
  conversation.
- **`src/mondo/cli/_examples.py`** (1100 lines of epilog registry) —
  intentional per the help-system design (see `docs/help-system.md`).
- **Leaf command modules** (`board.py`, `item.py`, etc.) — do not touch.
  The whole safety case for this batch is "only main.py + one new helper
  module change."
- **Test files** (other than the new parity test) — the test contract is
  `from mondo.cli.main import app`, and it stays intact.

---

## 11. Estimated effort

- §5a (`_lazy.py`): 30 min — mostly typing the registry.
- §5b (`main.py` rewire): 15 min.
- §5c (`argv.py`): 15 min — depends on what the current impl looks like.
- §5d (help dump-spec force-load): 15 min.
- §7 (parity test): 45 min.
- Verification + iteration: 30–60 min.

**Total: 2½–3 hours** for a focused session.
