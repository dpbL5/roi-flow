@echo off
setlocal

set "FLOW_URL=https://labs.google/fx/tools/flow"
set "CDP_PORT=9223"
if "%FLOW_CHROME_USER_DATA_DIR%"=="" (
  set "FLOW_CHROME_USER_DATA_DIR=%LOCALAPPDATA%\FlowVeoStudio\ChromeUserData"
)
set "CHROME_EXE="

if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
  set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
) else if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
  set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
) else (
  set "CHROME_EXE=chrome.exe"
)

echo Starting regular Google Chrome with CDP on port %CDP_PORT%.
echo.
echo Important:
echo - Close all Chrome windows before using this file.
echo - This uses a dedicated Chrome user-data-dir:
echo   %FLOW_CHROME_USER_DATA_DIR%
echo - Do not use the old projects\flow_browser_profile window.
echo - Optional: pass Chrome profile directory, for example:
echo   start-flow-chrome.bat "Profile 1"
echo.

if not "%~1"=="" (
  start "" "%CHROME_EXE%" --remote-debugging-port=%CDP_PORT% "--user-data-dir=%FLOW_CHROME_USER_DATA_DIR%" --no-first-run --no-default-browser-check "--profile-directory=%~1" "%FLOW_URL%"
) else (
  start "" "%CHROME_EXE%" --remote-debugging-port=%CDP_PORT% "--user-data-dir=%FLOW_CHROME_USER_DATA_DIR%" --no-first-run --no-default-browser-check "%FLOW_URL%"
)

endlocal
