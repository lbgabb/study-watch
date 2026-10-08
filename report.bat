@echo off
REM Study Watch - print today's report (extra args pass through, e.g. --days 7). ASCII only.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" --report %*
pause
