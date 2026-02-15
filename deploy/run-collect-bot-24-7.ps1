# Avatar Collect Bot — 24/7 runner (Windows)
# Запуск: powershell -ExecutionPolicy Bypass -File deploy/run-collect-bot-24-7.ps1
# Или: .\deploy\run-collect-bot-24-7.ps1
#
# Рекомендация: создать задачу в Планировщике задач:
#   Действие: powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\...\Avatar\deploy\run-collect-bot-24-7.ps1"
#   Триггер: при входе пользователя / при запуске ПК

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir "collect-bot-24-7.log"

function Write-Log { param($msg) $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"; Add-Content -Path $LogFile -Value "$ts $msg" }

Write-Log "=== Collect bot 24/7 started ==="

while ($true) {
    Write-Log "Starting collect_bot.py..."
    try {
        & python bot/collect_bot.py 2>&1 | ForEach-Object { Write-Log $_ }
    } catch {
        Write-Log "Exception: $_"
    }
    $exitCode = $LASTEXITCODE
    Write-Log "Bot exited with code $exitCode. Restarting in 10 seconds..."
    Start-Sleep -Seconds 10
}
