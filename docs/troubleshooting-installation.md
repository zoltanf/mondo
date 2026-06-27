# Troubleshooting installation

Things that can go wrong when installing `mondo`, and how to fix them.

Each scenario starts with the symptom (the exact error or behaviour a user
sees), then a quick diagnosis, then the fix.

---

## Scenario index

1. [`brew install` errors with "arm64 architecture is required" on an Apple Silicon Mac](#scenario-1-brew-install-errors-with-arm64-architecture-is-required-on-an-apple-silicon-mac)
2. [macOS: "`mondo` cannot be opened" / "`mondo` is damaged"](#scenario-2-macos-mondo-cannot-be-opened--mondo-is-damaged) (Gatekeeper)
3. [Windows: "Windows protected your PC" / SmartScreen blocks the binary](#scenario-3-windows-windows-protected-your-pc--smartscreen-blocks-the-binary)
4. [Windows: `mondo` not recognized after install (PATH not active yet)](#scenario-4-windows-mondo-not-recognized-after-install-path-not-active-yet)

---

## Scenario 1: `brew install` errors with "arm64 architecture is required" on an Apple Silicon Mac

### Symptom

`brew install zoltanf/mondo/mondo` fails with:

```
==> Fetching downloads for: mondo
mondo: The arm64 architecture is required for this software.
Error: mondo: An unsatisfied requirement failed this build.
```

…on a Mac with an M1 / M2 / M3 / M4 / M5 chip. The arm64 requirement should
already be satisfied, so the error is confusing.

### Diagnosis

The formula's `depends_on arch: :arm64` check reads **Homebrew's** notion of
the current architecture, not the hardware's. If Homebrew is running under
**Rosetta** (Apple's x86_64 translation layer), it reports the process arch
as `x86_64` and the formula refuses to install — even on Apple Silicon
hardware.

This happens when:

- Homebrew was installed via Rosetta and lives at `/usr/local/Homebrew/…`
  instead of `/opt/homebrew/…`. (The native Apple Silicon Homebrew prefix
  is `/opt/homebrew`; `/usr/local` is the legacy Intel prefix.)
- The Terminal app itself is set to "Open using Rosetta", so every command
  launched from it runs as x86_64.

Confirm with three commands in the same shell where the error happens:

```bash
which brew
# /opt/homebrew/bin/brew     → native arm64 Homebrew (good, error shouldn't happen)
# /usr/local/bin/brew        → x86_64 Homebrew under Rosetta (this is your problem)

uname -m
# arm64                      → shell is native (good)
# x86_64                     → shell is running under Rosetta (this is your problem)

sysctl -n machdep.cpu.brand_string
# "Apple M5" (or M1/M2/M3/M4) → hardware is actually Apple Silicon
```

If `which brew` shows `/usr/local/bin/brew` **or** `uname -m` shows `x86_64`,
this scenario applies.

### Fix

Three steps: remove the x86_64 Homebrew, install the native arm64 Homebrew,
re-install `mondo`.

**Optional — save the list of packages first.** Anything you had under
`/usr/local` will be gone after the uninstall, so capture the list if you
want to restore it later:

```bash
/usr/local/bin/brew leaves > ~/brew-packages.txt
```

**Step 1 — uninstall the x86_64 Homebrew at `/usr/local`.**

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/uninstall.sh)"
```

The uninstaller is interactive and asks before removing. It only touches
`/usr/local`, so if you have both prefixes installed it leaves `/opt/homebrew`
alone. Some empty directories may remain under `/usr/local` afterwards —
safe to leave, or `sudo rm -rf` if you prefer.

**Step 2 — make sure your shell is native arm64, then install Homebrew.**

If you set Terminal to "Open using Rosetta" at some point, undo that first:

> Finder → Applications → Utilities → right-click **Terminal** → **Get Info**
> → uncheck **Open using Rosetta** → quit Terminal and relaunch.

Then install the native Homebrew. Prefixing with `arch -arm64` is belt-and-
suspenders — even if the shell is somehow still under Rosetta, this forces
the installer to run as arm64:

```bash
arch -arm64 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

The installer puts `brew` at `/opt/homebrew/bin/brew` and prints two lines
about adding it to your shell's `PATH` — run them. They look roughly like:

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

**Step 3 — verify, then install `mondo`.**

```bash
which brew        # → /opt/homebrew/bin/brew
uname -m          # → arm64
brew install zoltanf/mondo/mondo
mondo --version
```

**Restore previous packages (optional).** If you saved `~/brew-packages.txt`
earlier:

```bash
xargs brew install < ~/brew-packages.txt
```

### Why not also publish a `darwin-x86_64` build?

A `darwin-x86_64` binary would run under Rosetta on Apple Silicon too, and
would sidestep this issue entirely. We don't ship one today because:

- Apple Silicon is the only macOS architecture supported by current Mac
  hardware sales since late 2020, and Apple's official Rosetta deprecation
  is in progress.
- The fix above is a one-time cleanup that leaves the user with a healthier
  Homebrew install (native, faster, fewer surprises).

If you have a genuine need (e.g. a fleet of older Intel Macs you can't
replace), install [from source](../README.md#from-source) — `uv sync
--all-extras && uv run mondo --version` works on any Mac.

---

## Scenario 2: macOS "`mondo` cannot be opened" / "`mondo` is damaged"

These dialogs come from Gatekeeper when you run a **directly-downloaded**
unsigned binary. `brew install` strips the quarantine attribute
automatically and does not trip this.

The fix is covered in detail in the README:
[macOS: working around Gatekeeper](../README.md#macos-working-around-gatekeeper-unidentified-developer).
Short version: `xattr -dr com.apple.quarantine ./mondo` (recursive — the
release archive extracts to a `mondo/` directory).

---

## Scenario 3: Windows "Windows protected your PC" / SmartScreen blocks the binary

### Symptom

After downloading the release `.zip` in a browser and launching `mondo.exe`
from Explorer, you see a blue dialog:

```
Windows protected your PC
Microsoft Defender SmartScreen prevented an unrecognized app from starting.
Running this app might put your PC at risk.
```

### Diagnosis

The Windows binaries are **unsigned** (no code-signing certificate — the same
reason macOS shows the Gatekeeper dialog in Scenario 2). SmartScreen flags
files that carry the "Mark of the Web" — an alternate data stream Windows adds
to anything downloaded through a browser — until the app builds reputation.

This mainly trips when you **double-click the `.exe` in Explorer**. Running
`mondo` from a terminal (PowerShell / cmd) usually isn't blocked, and the
recommended install paths avoid it entirely.

### Fix

**Best: use Scoop or the install script.** Neither goes through the
browser-download + Explorer-launch path that trips SmartScreen:

```powershell
scoop bucket add mondo https://github.com/zoltanf/scoop-mondo
scoop install mondo
# or:
irm https://raw.githubusercontent.com/zoltanf/mondo/main/scripts/install.ps1 | iex
```

**If you already downloaded the `.zip` and hit the dialog:**

- Click **More info** → **Run anyway** in the SmartScreen dialog, or
- Strip the Mark of the Web before extracting, so none of the files inherit
  it:

  ```powershell
  Unblock-File .\mondo-<ver>-windows-x86_64.zip
  Expand-Archive .\mondo-<ver>-windows-x86_64.zip
  # if you already extracted, unblock the whole directory instead:
  Get-ChildItem -Recurse .\mondo | Unblock-File
  ```

**Why unsigned?** Code-signing certificates cost money; for now we ship
unsigned Windows binaries to keep releases free. `scoop install` is the
low-friction path.

---

## Scenario 4: Windows `mondo` not recognized after install (PATH not active yet)

### Symptom

You just installed `mondo` (via `scripts/install.ps1`, Scoop, or by adding the
folder to PATH yourself), but the same terminal still says:

```
mondo : The term 'mondo' is not recognized as the name of a cmdlet, function,
script file, or operable program.
```

### Diagnosis

`PATH` changes only take effect for **newly launched** processes. Your current
terminal read its environment at startup and won't pick up an entry added
afterwards. The installers persist the change to your **user** PATH correctly —
the running shell just predates it.

### Fix

Simplest: **open a new terminal** and try again:

```powershell
mondo --version
```

To avoid reopening, reload PATH in the current PowerShell session:

```powershell
$env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
            [Environment]::GetEnvironmentVariable("Path", "Machine")
mondo --version
```

(`install.ps1` already updates the *current* session's PATH, so this mostly
affects Scoop installs and manual PATH edits, or a second terminal that was
open while you installed.)
