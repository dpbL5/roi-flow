@echo off
setlocal
cd /d "%~dp0"

.venv\Scripts\python desktop.py

if errorlevel 1 pause
endlocal
