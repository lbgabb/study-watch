@echo off
REM Study Watch - 25/5 pomodoro: start a plan, keep monitoring in background, show report at the end.
REM ASCII only (see README dev notes: Chinese bytes in .bat can break cmd parsing).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pomodoro.ps1" %*
echo.
echo ==== Daily report ====
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0report.bat" 2>nul
echo.
echo Tip: open the dashboard to watch the countdown and skip breaks.
pause
