# Run on the VPS, after copying mt5_bridge_release.zip there (e.g. via RDP
# into mt5_bridge\deploy\).
#
# Stops the running app, replaces code + frontend build in place, restarts.
#
# trades.db, .env and ticket_map_*.json are never part of the release zip,
# so this script physically cannot overwrite them — the only thing that
# changes is the code and frontend\dist. Schema changes apply themselves
# safely on the next start (init_db() uses idempotent CREATE TABLE IF NOT
# EXISTS / ALTER TABLE ... ADD COLUMN against the *existing* trades.db).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File mt5_bridge\deploy\apply_release.ps1
#   powershell -ExecutionPolicy Bypass -File mt5_bridge\deploy\apply_release.ps1 -ZipPath C:\path\to\other.zip
#   powershell -ExecutionPolicy Bypass -File mt5_bridge\deploy\apply_release.ps1 -NoRestart

param(
    [string]$ZipPath = "$PSScriptRoot\mt5_bridge_release.zip",
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
$deployDir = $PSScriptRoot            # mt5_bridge\deploy
$root      = Split-Path -Parent $deployDir   # mt5_bridge

if (-not (Test-Path $ZipPath)) {
    Write-Error "Release zip not found at $ZipPath. Copy it from the dev machine first."
    exit 1
}

Write-Host "==> Stopping running app_server.py / mt5_worker.py processes (if any)..."
$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -match "app_server\.py|mt5_worker\.py" }
foreach ($p in $procs) {
    Write-Host "    Killing PID $($p.ProcessId): $($p.CommandLine)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($procs) { Start-Sleep -Seconds 2 }

Write-Host "==> Extracting release..."
$tmp = Join-Path $env:TEMP "mt5_bridge_release_$(Get-Random)"
Expand-Archive -Path $ZipPath -DestinationPath $tmp -Force

Write-Host "==> Updating backend files..."
# Every .py at the zip root is a backend module, plus the fixed assets below.
# This used to be a hand-maintained list, which meant a release that ADDED a
# module silently shipped without it -- and because this script self-updates
# below, the stale copy on the VPS was always the one making that decision.
# Globbing removes that whole class of failure.
$deployOnly = @("apply_release.ps1", "check_open_positions.py")
$backend = @(Get-ChildItem -Path $tmp -Filter *.py -File | Where-Object { $deployOnly -notcontains $_.Name } | Select-Object -ExpandProperty Name)
$backend += @("signal_alert.wav", "requirements.txt")
foreach ($f in $backend) {
    $src = Join-Path $tmp $f
    if (Test-Path $src) {
        Write-Host "    $f"
        Copy-Item $src -Destination (Join-Path $root $f) -Force
    }
}

# Self-update: this script and its companion never copy themselves, so without this
# the VPS keeps running whatever version of apply_release.ps1/check_open_positions.py
# happened to be on disk before -- silently ignoring new files added to the backend
# list above by a newer release (this is exactly how cloud_sync.py got missed once).
Write-Host "==> Updating deploy scripts for next time..."
foreach ($f in @("apply_release.ps1", "check_open_positions.py")) {
    $src = Join-Path $tmp $f
    if (Test-Path $src) {
        Copy-Item $src -Destination (Join-Path $deployDir $f) -Force
    }
}

Write-Host "==> Replacing frontend\dist (build output only, safe to fully swap)..."
$destDist = Join-Path $root "frontend\dist"
if (Test-Path $destDist) { Remove-Item $destDist -Recurse -Force }
Copy-Item (Join-Path $tmp "frontend\dist") -Destination $destDist -Recurse

Remove-Item $tmp -Recurse -Force

Write-Host ""
Write-Host "==> Code updated. NOT touched: trades.db, .env, ticket_map_*.json"

if ($NoRestart) {
    Write-Host "==> -NoRestart passed, skipping app restart."
} else {
    Write-Host "==> Restarting app (run.bat)..."
    Start-Process -FilePath (Join-Path $root "run.bat") -WorkingDirectory $root
    Write-Host "==> Done."
}
