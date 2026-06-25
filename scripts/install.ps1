<#
.SYNOPSIS
    Install the mondo CLI on Windows (x86_64).

.DESCRIPTION
    Downloads the latest mondo release archive from GitHub, extracts it to
    %LOCALAPPDATA%\Programs\mondo, and adds that directory to the user PATH.

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
    $latest = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" `
        -Headers @{ "User-Agent" = "mondo-install" }
    $Version = $latest.tag_name -replace '^v', ''
}
$Version = $Version -replace '^v', ''

$asset = "mondo-$Version-windows-x86_64.zip"
$url = "https://github.com/$Repo/releases/download/v$Version/$asset"

Write-Host "Installing mondo $Version -> $InstallDir"

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("mondo-install-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
try {
    $zip = Join-Path $tmp $asset
    Write-Host "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $zip

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
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$entries = ($userPath -split ';') | Where-Object { $_ -ne '' }
if ($entries -notcontains $InstallDir) {
    $newPath = (@($entries) + $InstallDir) -join ';'
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "Added $InstallDir to your user PATH."
    Write-Host "Open a new terminal for the PATH change to take effect."
}
if (($env:Path -split ';') -notcontains $InstallDir) {
    $env:Path = "$env:Path;$InstallDir"
}

Write-Host ""
& (Join-Path $InstallDir "mondo.exe") --version
Write-Host "mondo installed. Run 'mondo --help' to get started."
