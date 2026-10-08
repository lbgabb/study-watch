@echo off
REM Study Watch - 25 minute pomodoro session, then print the daily report. ASCII only.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" --minutes 25
echo.
echo ==== Daily report ====
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" --report
pause
