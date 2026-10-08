@echo off
REM Study Watch launcher - ASCII only on purpose.
REM cmd.exe parses this file with the system ANSI code page, and a BOM/Chinese
REM text here breaks "@echo off" (cmd tries to run the mangled bytes as a command).
REM Keep this file ASCII; all Chinese UI text lives in launch.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0launch.ps1"
exit /b 0
