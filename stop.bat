@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
if /I "%~1"=="--no-pause" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%stop.ps1"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%stop.ps1" %*
)
set "STATUS=%ERRORLEVEL%"

if not "%~1"=="--no-pause" if not "%CI%"=="true" if not "%NETWORK_AGENT_NO_PAUSE%"=="1" pause
exit /b %STATUS%
