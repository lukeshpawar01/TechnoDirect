# Build the dashboard for hosting: API calls go to /api on the same address.
# Run again after every frontend change, then restart the "TechnoDirect Dashboard" task (or the PC).
$ErrorActionPreference = "Stop"
$frontend = Resolve-Path (Join-Path $PSScriptRoot "..\..\..\Frontend")
Push-Location $frontend
try {
    $env:VITE_API_BASE_URL = "/api"
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    Write-Host "Built $frontend\dist"
} finally {
    Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
    Pop-Location
}
