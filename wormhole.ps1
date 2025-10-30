# PowerShell launcher to run the wormhole module with uv
# Usage:
#   ./wormhole.ps1 [args]
# Notes:
# - Requires uv (https://docs.astral.sh/uv/)
# - Env vars:
#     UV_SYNC=0   -> skip dependency sync (default is 1)
#     UV_ARGS     -> extra args passed to `uv run` (e.g., "--python 3.11")

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Move to the repository root (script's directory)
$scriptDir = Split-Path -Parent $PSCommandPath
Set-Location $scriptDir

# Check for uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Error "uv is not installed. Install from https://astral.sh/uv"
  exit 1
}

# Optional dependency sync
$doSync = $true
if ($env:UV_SYNC -and $env:UV_SYNC -eq '0') { $doSync = $false }

if ($doSync) {
  & uv sync --frozen
  if ($LASTEXITCODE -ne 0) {
    & uv sync
    if ($LASTEXITCODE -ne 0) {
      Write-Error "uv sync failed with exit code $LASTEXITCODE"
      exit $LASTEXITCODE
    }
  }
}

# Build uv run arguments
$uvArgs = @('run')
if ($env:UV_ARGS) {
  # Naive split; quote items with spaces inside UV_ARGS if needed
  $uvArgs += ($env:UV_ARGS -split ' ')
}
$uvArgs += @('-m', 'wormhole')
$uvArgs += $args

# Execute
& uv @uvArgs
exit $LASTEXITCODE
