# Thin PowerShell wrapper around scripts/publish_github.py.
# It is intentionally UTF-8 BOM safe for Windows PowerShell 5.1.
param(
    [string]$Owner = "",
    [string]$RepoName = "audiolab-studio",
    [ValidateSet("public", "private")]
    [string]$Visibility = "public",
    [string]$Description = "Local audio workbench: vocal/BGM classification, timbre clustering, ffmpeg processing.",
    [switch]$SkipRelease,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    $Py = "python"
}

$argsList = @(
    (Join-Path $Root "scripts\publish_github.py"),
    "--repo-name", $RepoName,
    "--visibility", $Visibility,
    "--description", $Description
)
if ($Owner) { $argsList += @("--owner", $Owner) }
if ($SkipRelease) { $argsList += "--skip-release" }
if ($DryRun) { $argsList += "--dry-run" }

Push-Location $Root
try {
    & $Py @argsList
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
