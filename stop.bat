@echo off
REM Study Watch - stop the background monitor. ASCII only.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-watch.ps1"
pause
