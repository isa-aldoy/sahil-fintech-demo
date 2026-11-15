@echo off
rem Double-click to set up and start Sahil. Runs the script in this folder only.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-and-run.ps1"
echo.
pause
