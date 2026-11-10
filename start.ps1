# Starts the full local stack on Windows (no Docker):
#   1. Neon WebSocket tunnel (needed because this network blocks raw Postgres port 5432)
#   2. FastAPI backend on :8000
#   3. Vite React UI on :5173
# Usage:  powershell -ExecutionPolicy Bypass -File .\start.ps1
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$neonHost = 'ep-proud-glitter-bdx1c5el-pooler.c-8.us-east-2.aws.neon.tech'

function Stop-Matching($pattern) {
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match $pattern } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
Stop-Matching 'neon_tunnel'; Stop-Matching 'uvicorn app.main'; Stop-Matching 'vite'; Stop-Matching 'bridge.py'

Start-Process node -ArgumentList "tools/neon_tunnel.mjs", $neonHost -WorkingDirectory $root -WindowStyle Hidden
Start-Sleep 2
# 4. FXCM market-data bridge (portable Python 3.7, read-only: quotes + candles, never orders)
Start-Process "$root\fxcm_bridge\runtime\python.exe" -ArgumentList "-u", "bridge.py" -WorkingDirectory "$root\fxcm_bridge" -WindowStyle Hidden -RedirectStandardOutput "$root\fxcm_bridge\bridge.log" -RedirectStandardError "$root\fxcm_bridge\bridge.err.log"
Start-Process "$root\backend\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "8000" -WorkingDirectory "$root\backend" -WindowStyle Hidden
Start-Process cmd.exe -ArgumentList "/c", "npm run dev" -WorkingDirectory "$root\frontend" -WindowStyle Hidden
Start-Sleep 6
Write-Host "UI:  http://localhost:5173"
Write-Host "API: http://localhost:8000/api/status"
Start-Process "http://localhost:5173"
