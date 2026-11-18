# Scheduled data refresh (10:00 and 18:00 via the "TechnoDirect Refresh" task). Safe to run by hand any time.
$backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$logs = Join-Path $backend "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$env:TD_ENV_FILE = Join-Path $backend ".env.production"
Set-Location $backend
"`n===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') refresh =====" | Out-File -Append -Encoding utf8 (Join-Path $logs "refresh.log")
& (Join-Path $backend ".venv\Scripts\python.exe") manage.py scheduled_refresh *>> (Join-Path $logs "refresh.log")
exit $LASTEXITCODE
