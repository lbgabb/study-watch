@echo off
REM Study Watch - continuous monitoring (console window). ASCII only.
REM All Chinese UI text lives in start.ps1 (UTF-8 with BOM).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
echo.
pause
