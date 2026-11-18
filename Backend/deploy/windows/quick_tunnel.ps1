# TEMPORARY test link: https://<random>.trycloudflare.com -> this PC's dashboard (no domain or Cloudflare setup needed).
#   Run in PowerShell **as Administrator**:
#     cd C:\Users\IT\Desktop\TechnoDirect\Backend\deploy\windows
#     Set-ExecutionPolicy -Scope Process Bypass; .\quick_tunnel.ps1
# The link works while this window stays open. Close the window (or Ctrl+C) to take it offline.
# A new random link is created every time. It is public, so share it only with testers (app login still applies).
$ErrorActionPreference = "Stop"
$backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$python = Join-Path $backend ".venv\Scripts\python.exe"
$logs = Join-Path $backend "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$health = "http://127.0.0.1:8080/api/health/"

function Test-Dashboard {
    try { (Invoke-WebRequest -UseBasicParsing $health -TimeoutSec 5).StatusCode -eq 200 } catch { $false }
}

# 1. cloudflared
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "Installing cloudflared..."
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) { throw "cloudflared not found after install - open a new PowerShell window and run this again." }
}

# 2. let the dashboard accept *.trycloudflare.com, then (re)start it so it reads the setting
& $python (Join-Path $PSScriptRoot "make_env_production.py") --quick-tunnel
$task = Get-ScheduledTask -TaskName "TechnoDirect Dashboard" -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Restarting the 'TechnoDirect Dashboard' task..."
    Stop-ScheduledTask -TaskName "TechnoDirect Dashboard"
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*serve.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-ScheduledTask -TaskName "TechnoDirect Dashboard"
} else {
    Write-Host "Dashboard task not installed (run install_tasks.ps1 for auto-start) - starting it in a separate window..."
    if (-not (Test-Path (Join-Path $backend "..\Frontend\dist\index.html"))) { & (Join-Path $PSScriptRoot "build_frontend.ps1") }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*serve.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Process powershell -WindowStyle Minimized -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\start_dashboard.ps1`""
}
Write-Host "Waiting for the dashboard..." -NoNewline
for ($i = 0; $i -lt 60 -and -not (Test-Dashboard); $i++) { Start-Sleep -Seconds 2; Write-Host "." -NoNewline }
Write-Host ""
if (-not (Test-Dashboard)) { throw "Dashboard is not answering on $health - see $logs\server.log" }

# 3. the tunnel (runs in this window; its log is kept to find the link)
$cfLog = Join-Path $logs "quick_tunnel.log"
Remove-Item $cfLog -ErrorAction SilentlyContinue
$cf = Start-Process cloudflared -ArgumentList "tunnel --no-autoupdate --url http://127.0.0.1:8080" -NoNewWindow -PassThru `
    -RedirectStandardError $cfLog -RedirectStandardOutput (Join-Path $logs "quick_tunnel.out.log")
try {
    $url = $null
    for ($i = 0; $i -lt 60 -and -not $url; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path $cfLog) {
            $m = Select-String -Path $cfLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
            if ($m) { $url = $m.Matches[0].Value }
        }
        if ($cf.HasExited) { throw "cloudflared stopped - see $cfLog" }
    }
    if (-not $url) { throw "No link from cloudflared after 60 s - see $cfLog" }
    $url | Set-Content -Encoding utf8 (Join-Path $logs "quick_tunnel_url.txt")
    Write-Host ""
    Write-Host "  Dashboard test link:  $url" -ForegroundColor Green
    Write-Host "  (also saved in $logs\quick_tunnel_url.txt)"
    Write-Host "  Keep this window open while people test. Close it or press Ctrl+C to take the link offline."
    Write-Host ""
    Wait-Process -Id $cf.Id
} finally {
    if (-not $cf.HasExited) { Stop-Process -Id $cf.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "Test link closed."
}
