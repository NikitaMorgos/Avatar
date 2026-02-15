@echo off
REM Avatar Collect Bot — 24/7 runner (Windows)
REM Запуск: двойной клик или deploy\run-collect-bot-24-7.bat
REM Для автозапуска при входе: добавить ярлык в Автозагрузку (shell:startup)

cd /d "%~dp0.."

:loop
python bot/collect_bot.py
echo [%date% %time%] Bot exited, restarting in 10 sec...
timeout /t 10 /nobreak > nul
goto loop
