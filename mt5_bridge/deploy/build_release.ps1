# Run on the DEV machine.
#
# Builds the React frontend and packages everything the VPS needs into a
# single zip: mt5_bridge/deploy/mt5_bridge_release.zip
#
# Deliberately NOT included (so the VPS's live state is never touched):
#   trades.db, .env, ticket_map_*.json, __pycache__, node_modules,
#   test_*.py, static/, templates/, fix_*.py, scratch.py
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File mt5_bridge\deploy\build_release.ps1

$ErrorActionPreference = "Stop"

$deployDir = $PSScriptRoot                          # mt5_bridge\deploy
$root      = Split-Path -Parent $deployDir           # mt5_bridge
$frontend  = Join-Path $root "frontend"
$stage     = Join-Path $deployDir "_stage"
$zipPath   = Join-Path $deployDir "mt5_bridge_release.zip"

Write-Host "==> Building frontend (npm run build)..."
Push-Location $frontend
npm run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
Pop-Location

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null

Write-Host "==> Staging backend files..."
$filesToCopy = @(
    "app_server.py",
    "mt5_worker.py",
    "news_calendar.py",
    "cloud_sync.py",
    "signal_alert.wav",
    "requirements.txt"
)
foreach ($f in $filesToCopy) {
    $src = Join-Path $root $f
    if (Test-Path $src) {
        Copy-Item $src -Destination $stage
    } else {
        Write-Warning "Skipping missing file: $f"
    }
}

# Ship the safety-check + apply scripts alongside the code so the VPS
# always has the matching version of both.
Copy-Item (Join-Path $deployDir "apply_release.ps1") -Destination $stage
Copy-Item (Join-Path $deployDir "check_open_positions.py") -Destination $stage

Write-Host "==> Staging frontend build (dist/)..."
New-Item -ItemType Directory -Path (Join-Path $stage "frontend") | Out-Null
Copy-Item (Join-Path $frontend "dist") -Destination (Join-Path $stage "frontend\dist") -Recurse

Write-Host "==> Zipping..."
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zipPath
Remove-Item $stage -Recurse -Force

Write-Host ""
Write-Host "==> Done: $zipPath"
Write-Host "    Copy this ONE file to the VPS (e.g. into mt5_bridge\deploy\ there),"
Write-Host "    then run apply_release.ps1 on the VPS."
