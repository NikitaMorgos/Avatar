# SSH SOCKS5-туннель — автозапуск с reconnect
# Использование: .\tasks\task-001-vpn-proxy\jobs\start-tunnel.ps1 -VpsIp "1.2.3.4"
# После копирования в deploy/: .\deploy\start-tunnel.ps1 -VpsIp "1.2.3.4"

param(
    [string]$VpsIp = $env:VPS_IP,
    [int]$LocalPort = 1080,
    [string]$SshUser = "root",
    [string]$SshKey = "$HOME\.ssh\timeweb_vpn"
)

if (-not $VpsIp) {
    Write-Host "Укажи IP VPS: -VpsIp '1.2.3.4' или задай переменную VPS_IP" -ForegroundColor Red
    exit 1
}

$LogDir = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir "tunnel.log"

function Write-Log { param($msg) $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"; $line = "$ts $msg"; Write-Host $line; Add-Content -Path $LogFile -Value $line }

Write-Log "=== SSH tunnel starting: socks5://127.0.0.1:$LocalPort -> $SshUser@$VpsIp ==="

$KeyArg = if (Test-Path $SshKey) { @("-i", $SshKey) } else { @() }

while ($true) {
    Write-Log "Connecting..."
    try {
        & ssh @KeyArg `
            -D $LocalPort `
            -N `
            -o "ServerAliveInterval=30" `
            -o "ServerAliveCountMax=3" `
            -o "ExitOnForwardFailure=yes" `
            -o "StrictHostKeyChecking=accept-new" `
            "$SshUser@$VpsIp"
    } catch {
        Write-Log "Exception: $_"
    }
    Write-Log "Tunnel disconnected. Retry in 5 sec..."
    Start-Sleep -Seconds 5
}
