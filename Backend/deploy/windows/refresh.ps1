# Refresh the data now, by hand (the dashboard server also does it by itself at 10:30 and 15:30 IST).
$backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$logs = Join-Path $backend "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$env:TD_ENV_FILE = Join-Path $backend ".env.production"
Set-Location $backend
"`n===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') refresh =====" | Out-File -Append -Encoding utf8 (Join-Path $logs "refresh.log")
& (Join-Path $backend ".venv\Scripts\python.exe") manage.py scheduled_refresh *>> (Join-Path $logs "refresh.log")
exit $LASTEXITCODE
