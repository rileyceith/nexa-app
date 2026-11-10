# Starts the Nexa backend, which also serves the frontend.
#   App:   http://localhost:8000/
#   Admin: http://localhost:8000/admin/
#
#   .\dev.ps1          local development
#   .\dev.ps1 -Share   also opens a temporary public link (Cloudflare quick tunnel, https://<random>.trycloudflare.com)
#                      and runs the server in a safer mode: debug off, a fresh random secret key, and /admin/ hidden from
#                      the public link (it still works at http://localhost:8000/admin/). Press Ctrl+C to stop sharing.
param([switch]$Share)
$ErrorActionPreference = 'Stop'
$port = 8000

if ($Share) {
    $cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
    if (-not $cloudflared) { throw 'cloudflared is not installed. Install it with: winget install Cloudflare.cloudflared' }
    $bytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $env:NEXA_SECRET_KEY = [Convert]::ToBase64String($bytes)
    $env:NEXA_DEBUG = '0'
    $env:NEXA_SERVE_FRONTEND = '1'
    $env:NEXA_CORS_ALLOW_LOCAL_DEV = '0'
    if ($env:NEXA_CORS_ORIGINS) {
        $env:NEXA_CORS_ORIGINS += ',https://localhost,capacitor://localhost'
    } else {
        $env:NEXA_CORS_ORIGINS = 'https://localhost,capacitor://localhost'
    }
    $env:NEXA_ALLOWED_HOSTS = 'localhost,127.0.0.1,.trycloudflare.com'
    $env:NEXA_CSRF_TRUSTED_ORIGINS = 'https://*.trycloudflare.com'
    $env:NEXA_ADMIN_LOCAL_ONLY = '1'
}

function Stop-NexaServer {
    # Django's auto-reloader leaves a parent process behind that respawns the server, so stop every process of the family.
    $old = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "manage\.py\s+runserver\s+$port\b" }
    foreach ($proc in $old) {
        Write-Host "Stopping the Nexa server (PID $($proc.ProcessId))"
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

# A runserver left over from an earlier session keeps answering with its old settings, so stop it first.
Stop-NexaServer

# Anything still listening is not a Nexa server, so refuse to start on top of it.
$deadline = (Get-Date).AddSeconds(8)
do {
    $busy = netstat -ano | Where-Object { $_ -match "^\s*TCP\s+\S+:$port\s+\S+\s+LISTENING\s+(\d+)" }
    if ($busy) { Start-Sleep -Milliseconds 300 }
} while ($busy -and (Get-Date) -lt $deadline)
if ($busy) {
    $pidText = ([regex]::Match(($busy | Select-Object -First 1), '(\d+)\s*$')).Groups[1].Value
    throw "Port $port is in use by another program (PID $pidText). Close it and run this script again."
}

Set-Location (Join-Path $PSScriptRoot 'backend')
python manage.py migrate --noinput
if ($LASTEXITCODE -ne 0) { throw 'migrate failed' }
python manage.py createcachetable
if ($LASTEXITCODE -ne 0) { throw 'createcachetable failed' }

Write-Host ''
Write-Host "Nexa:  http://localhost:$port/"
Write-Host "Admin: http://localhost:$port/admin/"
Write-Host ''

if (-not $Share) {
    python manage.py runserver $port
    return
}

# --insecure serves the admin's static files while debug is off.
Start-Process python -ArgumentList 'manage.py', 'runserver', $port, '--noreload', '--insecure' -NoNewWindow

# A quick tunnel is deleted by Cloudflare if its connection drops for a moment, and a deleted tunnel can never reconnect
# (cloudflared just retries "Tunnel not found" forever). So watch it and open a fresh one, with a new address, when that happens.
$tunnelLog = Join-Path $env:TEMP 'nexa-tunnel.log'
function Start-Tunnel {
    Remove-Item $tunnelLog -ErrorAction SilentlyContinue
    Start-Process $cloudflared -ArgumentList 'tunnel', '--no-autoupdate', '--url', "http://localhost:$port" `
        -RedirectStandardError $tunnelLog -RedirectStandardOutput "$tunnelLog.out" -WindowStyle Hidden -PassThru
}

Write-Host 'Opening the public link (it changes every time). Anyone with it can reach the sign-in page and create an account.'
Write-Host 'Press Ctrl+C to stop sharing.'
$tunnel = Start-Tunnel
$shown = $false
try {
    while ($true) {
        Start-Sleep -Seconds 3
        $text = if (Test-Path $tunnelLog) { Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue } else { '' }
        if (-not $shown -and $text -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
            $shown = $true
            Write-Host ''
            Write-Host "Public link: $($Matches[0])" -ForegroundColor Green
            Write-Host ''
        }
        if ($tunnel.HasExited -or $text -match 'Tunnel not found') {
            Write-Host 'Cloudflare dropped the tunnel. Opening a new one, so the link will change...' -ForegroundColor Yellow
            Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            $tunnel = Start-Tunnel
            $shown = $false
        }
    }
}
finally {
    if ($tunnel) { Stop-Process -Id $tunnel.Id -Force -ErrorAction SilentlyContinue }
    Stop-NexaServer
}
