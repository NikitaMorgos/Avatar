# Единый старт: SSH-туннель + Collect bot
# Использование: .\tasks\task-001-vpn-proxy\jobs\start-avatar.ps1 -VpsIp "1.2.3.4"

param(
    [string]$VpsIp = $env:VPS_IP,
    [int]$LocalPort = 1080,
    [string]$SshUser = "root",
    [string]$SshKey = "$HOME\.ssh\timeweb_vpn"
)

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $ProjectRoot

if (-not $VpsIp) {
    Write-Host "Укажи IP VPS: -VpsIp '1.2.3.4' или задай VPS_IP в .env/environment" -ForegroundColor Red
    exit 1
}

$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Write-Log { param($msg) $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"; Write-Host "$ts $msg" }

Write-Log "=== Avatar starting ==="

# 1. Запуск SSH-туннеля в отдельном окне
Write-Log "Starting SSH tunnel -> $SshUser@$VpsIp:$LocalPort..."
$KeyArg = if (Test-Path $SshKey) { "-i `"$SshKey`"" } else { "" }
$TunnelCmd = "ssh $KeyArg -D $LocalPort -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new $SshUser@$VpsIp"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "while(`$true) { $TunnelCmd; Start-Sleep 5 }" -WindowStyle Minimized

# 2. Дать туннелю время подняться
Write-Log "Waiting 3s for tunnel..."
Start-Sleep -Seconds 3

# 3. Запуск Collect bot с автоперезапуском
Write-Log "Starting Collect bot..."
while ($true) {
    Write-Log "Bot starting..."
    python bot/collect_bot.py 2>&1 | Tee-Object -FilePath (Join-Path $LogDir "collect-bot.log") -Append
    $code = $LASTEXITCODE
    Write-Log "Bot exited (code $code). Restart in 10s..."
    Start-Sleep -Seconds 10
}
