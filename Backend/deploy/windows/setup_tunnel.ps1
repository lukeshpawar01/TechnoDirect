# Publish the dashboard on https://<Domain> with a Cloudflare Tunnel (run in PowerShell **as Administrator**):
#   Set-ExecutionPolicy -Scope Process Bypass; .\setup_tunnel.ps1 -Domain dashboard.technosport.in
#
# Needs: a free Cloudflare account, and your domain (technosport.in) added to Cloudflare. A browser window opens
# once to log in and pick the domain. No router or firewall ports are opened: the tunnel connects outwards.
param([Parameter(Mandatory = $true)][string]$Domain, [string]$TunnelName = "technodirect")

$ErrorActionPreference = "Stop"
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "Installing cloudflared..."
    winget install --id Cloudflare.cloudflared -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

$cfDir = Join-Path $env:USERPROFILE ".cloudflared"
if (-not (Test-Path (Join-Path $cfDir "cert.pem"))) {
    Write-Host "A browser window will open: log in to Cloudflare and choose your domain."
    cloudflared tunnel login
}

$existing = cloudflared tunnel list --output json | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName }
if (-not $existing) { cloudflared tunnel create $TunnelName | Out-Host }
$tunnel = cloudflared tunnel list --output json | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName }
$id = $tunnel.id

cloudflared tunnel route dns $TunnelName $Domain | Out-Host

# config for the Windows service (runs as SYSTEM, so it lives next to cloudflared's system config)
$sysDir = "C:\Windows\System32\config\systemprofile\.cloudflared"
New-Item -ItemType Directory -Force $sysDir | Out-Null
Copy-Item (Join-Path $cfDir "$id.json") $sysDir -Force
@"
tunnel: $id
credentials-file: $sysDir\$id.json
ingress:
  - hostname: $Domain
    service: http://127.0.0.1:8080
  - service: http_status:404
"@ | Set-Content -Encoding utf8 (Join-Path $sysDir "config.yml")

try { cloudflared service install | Out-Host } catch { Write-Host "cloudflared service already installed - restarting it" }
Restart-Service cloudflared -ErrorAction SilentlyContinue

# make sure the dashboard accepts the domain
& (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) ".venv\Scripts\python.exe") (Join-Path $PSScriptRoot "make_env_production.py") --domain $Domain
Restart-ScheduledTask -TaskName "TechnoDirect Dashboard" -ErrorAction SilentlyContinue
if (-not $?) { Stop-ScheduledTask "TechnoDirect Dashboard"; Start-ScheduledTask "TechnoDirect Dashboard" }

Write-Host "Done. In a minute or two: https://$Domain" -ForegroundColor Green
Write-Host "Recommended: Cloudflare dashboard > Zero Trust > Access > add an application for $Domain allowing only @technosport.in emails."
