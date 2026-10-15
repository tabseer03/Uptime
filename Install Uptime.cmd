@echo off
rem Double-click to install (or update) Uptime.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\install.ps1"
echo.
pause
