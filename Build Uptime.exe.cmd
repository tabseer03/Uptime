@echo off
rem Double-click to build dist\Uptime.exe, a single file that runs without Python.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\build.ps1"
echo.
pause
