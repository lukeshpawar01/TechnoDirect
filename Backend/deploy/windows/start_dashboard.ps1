# Start the hosted dashboard (waitress on 127.0.0.1:8080). Used by the "TechnoDirect Dashboard" scheduled task.
# The task restarts it if it stops.
$backend = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$logs = Join-Path $backend "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$env:TD_ENV_FILE = Join-Path $backend ".env.production"
Set-Location $backend
& (Join-Path $backend ".venv\Scripts\python.exe") serve.py *>> (Join-Path $logs "server.log")
exit $LASTEXITCODE
