@echo off
REM Study Watch - open the local dashboard in a browser. ASCII only.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dashboard.ps1"
