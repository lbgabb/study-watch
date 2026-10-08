@echo off
REM Study Watch - run all self tests. ASCII only.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0selftest.ps1"
pause
