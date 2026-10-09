@echo off
rem 独立桌宠窗口：双击即开（关掉窗口即结束）
rem 纯 ASCII，中文文案交给 ps1（见项目的编码约定）
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pet.ps1" %*
