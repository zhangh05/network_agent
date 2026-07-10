@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8010"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5173"
set "BACKEND_PID_FILE=%ROOT%\.backend.pid"
set "FRONTEND_PID_FILE=%ROOT%\.frontend.pid"
set "STATUS=0"

call :stop_service frontend %FRONTEND_PORT% "%FRONTEND_PID_FILE%" "vite"
if errorlevel 1 set "STATUS=1"
call :stop_service backend %BACKEND_PORT% "%BACKEND_PID_FILE%" "backend"
if errorlevel 1 set "STATUS=1"

if /I not "%~1"=="--no-pause" pause
exit /b %STATUS%

:stop_service
set "ROLE=%~1"
set "PORT=%~2"
set "PID_FILE=%~3"
set "PATTERN=%~4"
set "STOPPED=0"

if exist "%PID_FILE%" (
    set "PID="
    set /p PID=<"%PID_FILE%"
    if defined PID (
        call :stop_pid "%ROLE%" "!PID!" "%PATTERN%"
        if not errorlevel 1 set "STOPPED=1"
    )
)

for /f %%P in ('powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"') do (
    call :stop_pid "%ROLE%" "%%P" "%PATTERN%"
    if not errorlevel 1 set "STOPPED=1"
)

if exist "%PID_FILE%" del /q "%PID_FILE%"
if "%STOPPED%"=="0" (
    echo [%ROLE%] Not running.
)
exit /b 0

:stop_pid
set "ROLE=%~1"
set "PID=%~2"
set "PATTERN=%~3"
if not defined PID exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=%PID%' -ErrorAction SilentlyContinue; if(-not $p -or $p.CommandLine -notmatch '%PATTERN%'){exit 2}; Stop-Process -Id %PID% -ErrorAction Stop; exit 0" 2>nul
if errorlevel 2 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$p=Get-Process -Id %PID% -ErrorAction SilentlyContinue; if(-not $p -or $p.Path -notmatch '%PATTERN%'){exit 2}; Stop-Process -Id %PID% -ErrorAction Stop; exit 0" 2>nul
    if errorlevel 2 (
        echo [%ROLE%] Refusing to stop unverified process ^(PID %PID%^).
        exit /b 1
    )
)
if errorlevel 1 (
    echo [%ROLE%] Failed to stop PID %PID%.
    exit /b 1
)
echo [%ROLE%] Stopped PID %PID%.
exit /b 0
