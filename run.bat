@echo off
setlocal
cd /d "%~dp0"

set "URL=http://127.0.0.1:8765"
set "PY=.venv\Scripts\python.exe"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$url='%URL%';" ^
  "$ready=$false;" ^
  "try { $r=Invoke-RestMethod ($url + '/api/health') -TimeoutSec 1; $ready=$true } catch { }" ^
  "if (-not $ready) {" ^
  "  Start-Process -FilePath '%PY%' -ArgumentList '-u','app.py' -WorkingDirectory (Get-Location).Path -WindowStyle Minimized;" ^
  "  for ($i=0; $i -lt 30; $i++) {" ^
  "    try { $r=Invoke-RestMethod ($url + '/api/health') -TimeoutSec 1; $ready=$true; break } catch { Start-Sleep -Milliseconds 500 }" ^
  "  }" ^
  "}" ^
  "if ($ready) { exit 0 } else { Write-Host 'Server khong khoi dong duoc. Chay .venv\Scripts\python app.py de xem loi.'; exit 1 }"

if errorlevel 1 (
  pause
  exit /b 1
)

if /i "%~1"=="--no-open" (
  echo Server da san sang: %URL%
  exit /b 0
)

start "" "%URL%"

endlocal
