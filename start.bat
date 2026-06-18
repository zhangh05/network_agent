@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Network Agent

set "ROOT=%~dp0"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8010"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5173"
if "%INSTALL_DEPS%"=="" set "INSTALL_DEPS=auto"
set "LOG_DIR=%ROOT%workspace\logs"
set "BACKEND_PID_FILE=%ROOT%.backend.pid"
set "FRONTEND_PID_FILE=%ROOT%.frontend.pid"

echo Network Agent
echo Checking Python 3.12+ and Node.js 18+...

set "PYTHON="
for %%P in (py python python3) do (
    if not defined PYTHON (
        %%P -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
        if not errorlevel 1 set "PYTHON=%%P"
    )
)
if not defined PYTHON (
    echo [ERROR] Python 3.12+ is required.
    exit /b 1
)

node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js 18+ is required.
    exit /b 1
)

if /I not "%INSTALL_DEPS%"=="false" if not "%INSTALL_DEPS%"=="0" (
    %PYTHON% -c "import flask, flask_sock, yaml, langgraph, bs4, lxml, pdfplumber, scapy" >nul 2>&1
    if errorlevel 1 (
        %PYTHON% -m pip install -r "%ROOT%requirements.txt"
        if errorlevel 1 exit /b 1
    )
    if not exist "%ROOT%frontend\node_modules\.bin\vite.cmd" (
        pushd "%ROOT%frontend"
        call npm install
        if errorlevel 1 (
            popd
            exit /b 1
        )
        popd
    )
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

call :adopt backend %BACKEND_PORT% "%BACKEND_PID_FILE%" "backend[\\/]main.py"
if errorlevel 2 exit /b 1
if errorlevel 1 (
    echo [backend] Starting on port %BACKEND_PORT%...
    powershell -NoProfile -Command "$p=Start-Process -FilePath '%PYTHON%' -ArgumentList @('%ROOT%backend\main.py','--host','0.0.0.0','--port','%BACKEND_PORT%') -WorkingDirectory '%ROOT%' -RedirectStandardOutput '%LOG_DIR%\backend.log' -RedirectStandardError '%LOG_DIR%\backend.error.log' -WindowStyle Hidden -PassThru; $p.Id | Set-Content '%BACKEND_PID_FILE%'"
    if errorlevel 1 exit /b 1
)
call :wait_url backend "http://127.0.0.1:%BACKEND_PORT%/api/health" "%BACKEND_PID_FILE%"
if errorlevel 1 (
    call "%ROOT%stop.bat" --no-pause
    echo [ERROR] Backend failed to start. See %LOG_DIR%\backend.error.log
    exit /b 1
)

call :adopt frontend %FRONTEND_PORT% "%FRONTEND_PID_FILE%" "vite[\\/]bin[\\/]vite.js"
if errorlevel 2 (
    call "%ROOT%stop.bat" --no-pause
    exit /b 1
)
if errorlevel 1 (
    echo [frontend] Starting on port %FRONTEND_PORT%...
    powershell -NoProfile -Command "$p=Start-Process -FilePath 'node' -ArgumentList @('%ROOT%frontend\node_modules\vite\bin\vite.js','--host','0.0.0.0','--port','%FRONTEND_PORT%') -WorkingDirectory '%ROOT%frontend' -RedirectStandardOutput '%LOG_DIR%\frontend.log' -RedirectStandardError '%LOG_DIR%\frontend.error.log' -WindowStyle Hidden -PassThru; $p.Id | Set-Content '%FRONTEND_PID_FILE%'"
    if errorlevel 1 (
        call "%ROOT%stop.bat" --no-pause
        exit /b 1
    )
)
call :wait_url frontend "http://127.0.0.1:%FRONTEND_PORT%" "%FRONTEND_PID_FILE%"
if errorlevel 1 (
    call "%ROOT%stop.bat" --no-pause
    echo [ERROR] Frontend failed to start. See %LOG_DIR%\frontend.error.log
    exit /b 1
)

echo.
echo Backend:  http://localhost:%BACKEND_PORT%
echo Frontend: http://localhost:%FRONTEND_PORT%
echo Stop with: stop.bat
exit /b 0

:adopt
set "ROLE=%~1"
set "PORT=%~2"
set "PID_FILE=%~3"
set "PATTERN=%~4"
set "OWNER_PID="
for /f %%P in ('powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){$c.OwningProcess}"') do set "OWNER_PID=%%P"
if not defined OWNER_PID exit /b 1
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=!OWNER_PID!'; if($p -and $p.CommandLine -match '%PATTERN%'){exit 0}else{exit 1}"
if errorlevel 1 (
    echo [ERROR] Port %PORT% is occupied by another process ^(PID !OWNER_PID!^).
    exit /b 2
)
> "%PID_FILE%" echo !OWNER_PID!
echo [%ROLE%] Already running on port %PORT% ^(PID !OWNER_PID!^).
exit /b 0

:wait_url
set "ROLE=%~1"
set "URL=%~2"
set "PID_FILE=%~3"
for /l %%I in (1,1,30) do (
    powershell -NoProfile -Command "try{Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%' | Out-Null; exit 0}catch{exit 1}"
    if not errorlevel 1 (
        echo [%ROLE%] Ready.
        exit /b 0
    )
    timeout /t 1 /nobreak >nul
)
exit /b 1
