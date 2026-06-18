@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8010"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5173"
set "BACKEND_PID_FILE=%ROOT%.backend.pid"
set "FRONTEND_PID_FILE=%ROOT%.frontend.pid"
set "STATUS=0"

call :stop_service frontend %FRONTEND_PORT% "%FRONTEND_PID_FILE%" "vite[\\/]bin[\\/]vite.js"
if errorlevel 1 set "STATUS=1"
call :stop_service backend %BACKEND_PORT% "%BACKEND_PID_FILE%" "backend[\\/]main.py"
if errorlevel 1 set "STATUS=1"

if /I not "%~1"=="--no-pause" pause
exit /b %STATUS%

:stop_service
set "ROLE=%~1"
set "PORT=%~2"
set "PID_FILE=%~3"
set "PATTERN=%~4"
set "PID="

if exist "%PID_FILE%" set /p PID=<"%PID_FILE%"
if defined PID (
    powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=!PID!' -ErrorAction SilentlyContinue; if($p -and $p.CommandLine -match '%PATTERN%'){exit 0}else{exit 1}"
    if errorlevel 1 set "PID="
)
if not defined PID (
    for /f %%P in ('powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){$c.OwningProcess}"') do set "PID=%%P"
)
if not defined PID (
    echo [%ROLE%] Not running.
    if exist "%PID_FILE%" del /q "%PID_FILE%"
    exit /b 0
)

powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=!PID!' -ErrorAction SilentlyContinue; if(-not $p -or $p.CommandLine -notmatch '%PATTERN%'){exit 1}; Stop-Process -Id !PID! -ErrorAction Stop"
if errorlevel 1 (
    echo [%ROLE%] Refusing to stop unverified process on port %PORT% ^(PID !PID!^).
    if exist "%PID_FILE%" del /q "%PID_FILE%"
    exit /b 1
)
if exist "%PID_FILE%" del /q "%PID_FILE%"
echo [%ROLE%] Stopped ^(PID !PID!^).
exit /b 0
