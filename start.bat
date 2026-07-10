@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Network Agent

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8010"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5173"
if "%BACKEND_HOST%"=="" set "BACKEND_HOST=0.0.0.0"
if "%FRONTEND_HOST%"=="" set "FRONTEND_HOST=0.0.0.0"
if "%INSTALL_DEPS%"=="" set "INSTALL_DEPS=auto"
if "%LOG_DIR%"=="" set "LOG_DIR=%ROOT%\logs"
set "BACKEND_PID_FILE=%ROOT%\.backend.pid"
set "FRONTEND_PID_FILE=%ROOT%\.frontend.pid"
set "BACKEND_LOG=%LOG_DIR%\backend-8010.log"
set "BACKEND_ERR=%LOG_DIR%\backend-8010.err.log"
set "FRONTEND_LOG=%LOG_DIR%\frontend-5173.log"
set "FRONTEND_ERR=%LOG_DIR%\frontend-5173.err.log"

echo Network Agent

call :find_python
if errorlevel 1 exit /b 1
call :find_pip
if errorlevel 1 exit /b 1
call :find_node
if errorlevel 1 exit /b 1
call :find_npm
if errorlevel 1 exit /b 1

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

if /I not "%INSTALL_DEPS%"=="false" if not "%INSTALL_DEPS%"=="0" (
    echo [deps] Checking Python dependencies...
    "%PYTHON_BIN%" -c "import flask, flask_sock, yaml, bs4, lxml, pdfplumber, scapy" >nul 2>&1
    if errorlevel 1 (
        "%PYTHON_BIN%" -m pip install -r "%ROOT%\requirements.txt"
        if errorlevel 1 exit /b 1
    )
    "%PYTHON_BIN%" -m pip check >nul
    if errorlevel 1 (
        echo [ERROR] Python dependency check failed.
        exit /b 1
    )

    echo [deps] Checking frontend dependencies...
    if not exist "%ROOT%\frontend\node_modules\vite\bin\vite.js" (
        pushd "%ROOT%\frontend"
        call "%NPM_BIN%" install
        if errorlevel 1 (
            popd
            exit /b 1
        )
        popd
    )
) else (
    echo [deps] Skipped ^(INSTALL_DEPS=%INSTALL_DEPS%^).
)

call :start_backend
if errorlevel 1 exit /b 1
call :start_frontend
if errorlevel 1 (
    call "%ROOT%\stop.bat" --no-pause
    exit /b 1
)

echo.
echo Backend API:  http://127.0.0.1:%BACKEND_PORT%
echo Frontend UI:  http://127.0.0.1:%FRONTEND_PORT%
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -ExpandProperty IPAddress"`) do (
    echo LAN UI:       http://%%I:%FRONTEND_PORT%
    echo LAN backend:  http://%%I:%BACKEND_PORT%
)
echo Logs:         %BACKEND_LOG%
echo               %FRONTEND_LOG%
echo Stop with:    stop.bat
exit /b 0

:find_python
if defined PYTHON_BIN (
    "%PYTHON_BIN%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
    if not errorlevel 1 exit /b 0
)
set "PYTHON_BIN="
for %%P in (py.exe python.exe python3.exe) do (
    if not defined PYTHON_BIN (
        for /f "usebackq delims=" %%X in (`where %%P 2^>nul`) do (
            if not defined PYTHON_BIN (
                "%%X" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>&1
                if not errorlevel 1 set "PYTHON_BIN=%%X"
            )
        )
    )
)
if not defined PYTHON_BIN (
    echo [ERROR] Python 3.12+ is required.
    exit /b 1
)
exit /b 0

:find_node
if defined NODE_BIN (
    "%NODE_BIN%" -e "process.exit(Number(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)" >nul 2>&1
    if not errorlevel 1 exit /b 0
)
set "NODE_BIN="
for /f "usebackq delims=" %%X in (`where node.exe 2^>nul`) do (
    if not defined NODE_BIN (
        "%%X" -e "process.exit(Number(process.versions.node.split('.')[0]) >= 18 ? 0 : 1)" >nul 2>&1
        if not errorlevel 1 set "NODE_BIN=%%X"
    )
)
if not defined NODE_BIN (
    echo [ERROR] Node.js 18+ is required.
    exit /b 1
)
exit /b 0

:find_npm
if defined NPM_BIN (
    if exist "%NPM_BIN%" exit /b 0
)
set "NPM_BIN="
for /f "usebackq delims=" %%X in (`where npm.cmd 2^>nul`) do (
    if not defined NPM_BIN set "NPM_BIN=%%X"
)
if not defined NPM_BIN (
    echo [ERROR] npm is required.
    exit /b 1
)
exit /b 0

:find_pip
"%PYTHON_BIN%" -c "import pip" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python pip is required. Install pip via ensurepip or your system package manager.
    exit /b 1
)
exit /b 0

:start_backend
call :adopt backend %BACKEND_PORT% "%BACKEND_PID_FILE%" "backend"
if errorlevel 2 exit /b 1
if not errorlevel 1 goto :backend_wait

echo [backend] Starting on %BACKEND_HOST%:%BACKEND_PORT%...
type nul > "%BACKEND_LOG%"
type nul > "%BACKEND_ERR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=Start-Process -FilePath '%PYTHON_BIN%' -ArgumentList @('%ROOT%\backend\main.py','--host','%BACKEND_HOST%','--port','%BACKEND_PORT%') -WorkingDirectory '%ROOT%' -RedirectStandardOutput '%BACKEND_LOG%' -RedirectStandardError '%BACKEND_ERR%' -WindowStyle Hidden -PassThru; $p.Id | Set-Content '%BACKEND_PID_FILE%'"
if errorlevel 1 exit /b 1

:backend_wait
call :wait_url backend "http://127.0.0.1:%BACKEND_PORT%/api/health" "%BACKEND_PID_FILE%"
if errorlevel 1 (
    echo [ERROR] Backend failed to start. See %BACKEND_LOG% and %BACKEND_ERR%
    exit /b 1
)
call :write_port_pid %BACKEND_PORT% "%BACKEND_PID_FILE%"
exit /b 0

:start_frontend
call :adopt frontend %FRONTEND_PORT% "%FRONTEND_PID_FILE%" "vite"
if errorlevel 2 exit /b 1
if not errorlevel 1 goto :frontend_wait

if not exist "%ROOT%\frontend\node_modules\vite\bin\vite.js" (
    echo [ERROR] Vite is not installed. Run start.bat with INSTALL_DEPS=auto.
    exit /b 1
)
echo [frontend] Starting on %FRONTEND_HOST%:%FRONTEND_PORT%...
type nul > "%FRONTEND_LOG%"
type nul > "%FRONTEND_ERR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=Start-Process -FilePath '%NODE_BIN%' -ArgumentList @('%ROOT%\frontend\node_modules\vite\bin\vite.js','--host','%FRONTEND_HOST%','--port','%FRONTEND_PORT%') -WorkingDirectory '%ROOT%\frontend' -RedirectStandardOutput '%FRONTEND_LOG%' -RedirectStandardError '%FRONTEND_ERR%' -WindowStyle Hidden -PassThru; $p.Id | Set-Content '%FRONTEND_PID_FILE%'"
if errorlevel 1 exit /b 1

:frontend_wait
call :wait_url frontend "http://127.0.0.1:%FRONTEND_PORT%" "%FRONTEND_PID_FILE%"
if errorlevel 1 (
    echo [ERROR] Frontend failed to start. See %FRONTEND_LOG% and %FRONTEND_ERR%
    exit /b 1
)
call :write_port_pid %FRONTEND_PORT% "%FRONTEND_PID_FILE%"
exit /b 0

:adopt
set "ROLE=%~1"
set "PORT=%~2"
set "PID_FILE=%~3"
set "PATTERN=%~4"
set "OWNER_PID="
for /f %%P in ('powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){$c.OwningProcess}"') do set "OWNER_PID=%%P"
if not defined OWNER_PID exit /b 1
powershell -NoProfile -Command "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=!OWNER_PID!' -ErrorAction SilentlyContinue; if($p -and $p.CommandLine -match '%PATTERN%'){exit 0}else{exit 1}" 2>nul
if errorlevel 1 (
    powershell -NoProfile -Command "$p=Get-Process -Id !OWNER_PID! -ErrorAction SilentlyContinue; if($p -and $p.Path -match '%PATTERN%'){exit 0}else{exit 1}" 2>nul
    if errorlevel 1 (
        echo [ERROR] Port %PORT% is occupied by another process ^(PID !OWNER_PID!^).
        exit /b 2
    )
)
> "%PID_FILE%" echo !OWNER_PID!
echo [%ROLE%] Already running on port %PORT% ^(PID !OWNER_PID!^).
exit /b 0

:write_port_pid
set "PORT=%~1"
set "PID_FILE=%~2"
for /f %%P in ('powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){$c.OwningProcess}"') do (
    > "%PID_FILE%" echo %%P
)
exit /b 0

:wait_url
set "ROLE=%~1"
set "URL=%~2"
set "PID_FILE=%~3"
for /l %%I in (1,1,40) do (
    powershell -NoProfile -Command "try{Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%URL%' | Out-Null; exit 0}catch{exit 1}"
    if not errorlevel 1 (
        echo [%ROLE%] Ready.
        exit /b 0
    )
    timeout /t 1 /nobreak >nul
)
exit /b 1
