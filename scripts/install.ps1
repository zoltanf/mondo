<#
.SYNOPSIS
    Install the mondo CLI on Windows (x86_64).

.DESCRIPTION
    Downloads the latest mondo release archive from GitHub, verifies its
    SHA256 checksum, extracts it to %LOCALAPPDATA%\Programs\mondo, and adds
    that directory to the user PATH.

    Intended for the one-liner:

        irm https://raw.githubusercontent.com/zoltanf/mondo/main/scripts/install.ps1 | iex

    Pin a specific version by setting $env:MONDO_VERSION (e.g. "0.11.0")
    before running. No admin rights required — installs per-user.
#>

$ErrorActionPreference = "Stop"

$Repo = "zoltanf/mondo"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\mondo"

# Resolve the version: explicit override, else the latest GitHub release.
$Version = $env:MONDO_VERSION
if (-not $Version) {
    Write-Host "Resolving latest mondo release..."
    $latest = Invoke-RestMethod -UseBasicParsing `
        -Uri "https://api.github.com/repos/$Repo/releases/latest" `
        -Headers @{ "User-Agent" = "mondo-install" }
    $Version = $latest.tag_name -replace '^v', ''
}
$Version = $Version -replace '^v', ''

$asset = "mondo-$Version-windows-x86_64.zip"
$base = "https://github.com/$Repo/releases/download/v$Version"

Write-Host "Installing mondo $Version -> $InstallDir"

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("mondo-install-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
    $zip = Join-Path $tmp $asset
    Write-Host "Downloading $base/$asset"
    Invoke-WebRequest -UseBasicParsing -Uri "$base/$asset" -OutFile $zip

    # Verify the SHA256 against the release's SHA256SUMS.txt. Releases predating
    # the checksum file (older pinned versions) skip verification — HTTPS to
    # github.com still authenticates the transport.
    try {
        $sums = (Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS.txt").Content
    } catch {
        $sums = $null
    }
    if ($sums) {
        $line = ($sums -split "`n") |
            Where-Object { $_ -match [regex]::Escape($asset) } | Select-Object -First 1
        if (-not $line) { throw "no checksum for $asset in SHA256SUMS.txt" }
        $expected = (($line -split '\s+') | Where-Object { $_ })[0].ToLower()
        $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $expected) {
            throw "SHA256 mismatch for ${asset}:`n  expected $expected`n  actual   $actual"
        }
        Write-Host "Verified SHA256 checksum."
    } else {
        Write-Warning "SHA256SUMS.txt not published for v$Version - skipping integrity check."
    }

    Expand-Archive -Path $zip -DestinationPath $tmp -Force

    # The archive contains a single top-level mondo\ directory (PyInstaller
    # onedir): mondo.exe plus its _internal\ runtime. Move its contents so the
    # exe lands directly in $InstallDir.
    $extracted = Join-Path $tmp "mondo"
    if (-not (Test-Path (Join-Path $extracted "mondo.exe"))) {
        throw "unexpected archive layout: mondo\mondo.exe not found in $asset"
    }

    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Move-Item -Path (Join-Path $extracted "*") -Destination $InstallDir -Force
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

# Add $InstallDir to the user PATH (persisted) and the current session.
# Normalize entries (expand env vars, drop trailing slash, case-insensitive)
# so a cosmetically-different existing entry doesn't produce a duplicate.
function Get-NormalizedPath([string]$p) {
    if (-not $p) { return "" }
    return [Environment]::ExpandEnvironmentVariables($p).TrimEnd('\').ToLowerInvariant()
}
$targetNorm = Get-NormalizedPath $InstallDir
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$entries = ($userPath -split ';') | Where-Object { $_ -ne '' }
$present = $false
foreach ($e in $entries) { if ((Get-NormalizedPath $e) -eq $targetNorm) { $present = $true; break } }
if (-not $present) {
    $newPath = (@($entries) + $InstallDir) -join ';'
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "Added $InstallDir to your user PATH."
    Write-Host "Open a new terminal for the PATH change to take effect."
}
# Make mondo usable in the current session too.
$sessionNorm = ($env:Path -split ';') | ForEach-Object { Get-NormalizedPath $_ }
if ($sessionNorm -notcontains $targetNorm) {
    $env:Path = "$env:Path;$InstallDir"
}

Write-Host ""
& (Join-Path $InstallDir "mondo.exe") --version
Write-Host "mondo installed. Run 'mondo --help' to get started."
