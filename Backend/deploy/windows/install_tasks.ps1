# One-time setup (run in PowerShell **as Administrator**):
#   Set-ExecutionPolicy -Scope Process Bypass; .\install_tasks.ps1 -Domain dashboard.technosport.in
#
# 1. writes Backend\.env.production (secret key generated, DEBUG off, your domain allowed)
# 2. builds the dashboard (Frontend\dist)
# 3. registers two Windows scheduled tasks that run as SYSTEM, logged in or not:
#      "TechnoDirect Dashboard" - starts at boot, restarted every minute if it stops
#      "TechnoDirect Refresh"   - 10:00 and 18:00 every day
# 4. stops the PC sleeping while plugged in (the dashboard is offline while it sleeps)
param([string]$Domain = "")

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$backend = Resolve-Path (Join-Path $here "..\..")
$python = Join-Path $backend ".venv\Scripts\python.exe"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "Run this in PowerShell opened with 'Run as administrator'." }

Write-Host "1/4 Production settings"
if ($Domain) { & $python (Join-Path $here "make_env_production.py") --domain $Domain }
else { & $python (Join-Path $here "make_env_production.py") }

Write-Host "2/4 Building the dashboard"
& (Join-Path $here "build_frontend.ps1")

Write-Host "3/4 Scheduled tasks"
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

$serveAction = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\start_dashboard.ps1`""
$serveSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "TechnoDirect Dashboard" -Action $serveAction -Principal $principal `
    -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $serveSettings -Force | Out-Null

$refreshAction = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\refresh.ps1`""
$refreshSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$triggers = @((New-ScheduledTaskTrigger -Daily -At "10:00"), (New-ScheduledTaskTrigger -Daily -At "18:00"))
Register-ScheduledTask -TaskName "TechnoDirect Refresh" -Action $refreshAction -Principal $principal `
    -Trigger $triggers -Settings $refreshSettings -Force | Out-Null

Start-ScheduledTask -TaskName "TechnoDirect Dashboard"

Write-Host "4/4 Power: no sleep while plugged in"
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

Start-Sleep -Seconds 8
try {
    $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8080/api/health/" -TimeoutSec 20
    Write-Host "Dashboard is running: http://127.0.0.1:8080 ($($r.Content))" -ForegroundColor Green
} catch {
    Write-Host "Dashboard did not answer yet - see $backend\data\logs\server.log" -ForegroundColor Yellow
}
Write-Host "Next: run setup_tunnel.ps1 to publish it on https://$Domain"
