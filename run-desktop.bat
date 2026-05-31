@echo off
setlocal
cd /d "%~dp0"

python desktop.py

if errorlevel 1 pause
endlocal
