@echo off
title network_agent v2.3.1

set "ROOT=%~dp0"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=8010"
if "%FRONTEND_PORT%"=="" set "FRONTEND_PORT=5173"

echo.
echo  ========================================
echo    network_agent v2.3.1
echo    Auto Setup ^& Start
echo  ========================================
echo.

REM === 1. Python ===
echo  [1/4] Checking Python 3.10+ ...
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
    goto :python_found
)
python3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python3"
    goto :python_found
)
echo.
echo  [ERROR] Python is not installed or not in PATH.
echo          Please install Python 3.10+ from:
echo          https://www.python.org/downloads/
echo          IMPORTANT: Check "Add Python to PATH" during installation.
echo.
exit /b 1

:python_found
for /f "tokens=2" %%v in ('%PYTHON% --version 2^>^&1') do echo         OK -- Python %%v

REM === 2. Node.js ===
echo  [2/4] Checking Node.js 18+ ...
node --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Node.js is not installed or not in PATH.
    echo          Please install Node.js 18+ from:
    echo          https://nodejs.org/
    echo.
    exit /b 1
)
for /f %%v in ('node --version') do echo         OK -- Node.js %%v

REM === 3. Python deps ===
echo  [3/4] Installing Python dependencies (Tsinghua mirror) ...
cd /d "%ROOT%"

%PYTHON% -c "import flask" >nul 2>&1
if not errorlevel 1 (
    echo         Already installed -- skipping.
) else (
    echo         Downloading packages (may take 1-3 minutes) ...
    %PYTHON% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
    if errorlevel 1 (
        echo.
        echo  [ERROR] Failed to install Python packages.
        echo          Please check your network and try again.
        echo.
        exit /b 1
    )
    echo         OK
)

REM === 4. Frontend deps ===
echo  [4/4] Installing frontend dependencies (taobao mirror) ...
cd /d "%ROOT%frontend"

if exist "node_modules\" (
    echo         Already installed -- skipping.
) else (
    echo         First run -- downloading packages (may take 2-5 minutes) ...
    npm install --registry=https://registry.npmmirror.com
    if errorlevel 1 (
        echo.
        echo  [ERROR] npm install failed.
        echo          Please check your network and try again.
        echo.
        exit /b 1
    )
    echo         OK
)

REM === Start services ===
echo.
echo  ========================================
echo    Starting services ...
echo  ========================================
echo.

cd /d "%ROOT%"

if not exist "workspace\logs\" mkdir workspace\logs

echo  [backend] Starting on port %BACKEND_PORT% ...
start "network_agent_backend" /min cmd /c "%PYTHON% backend\main.py --host 0.0.0.0 --port %BACKEND_PORT% 1>workspace\logs\backend.log 2>&1"

echo  [backend] Waiting for health check ...
for /l %%i in (1,1,30) do (
    timeout /t 1 /nobreak >nul
    curl -s http://localhost:%BACKEND_PORT%/api/health >nul 2>&1
    if not errorlevel 1 (
        echo  [backend] Ready
        goto :backend_ok
    )
)
echo  [backend] Started (health check timed out -- may still be loading)
:backend_ok

cd /d "%ROOT%frontend"

echo  [frontend] Starting on port %FRONTEND_PORT% ...
start "network_agent_frontend" /min cmd /c "npx vite --host 0.0.0.0 --port %FRONTEND_PORT% 1>..\workspace\logs\frontend.log 2>&1"

echo  [frontend] Waiting for server ...
for /l %%i in (1,1,30) do (
    timeout /t 1 /nobreak >nul
    curl -s http://localhost:%FRONTEND_PORT% >nul 2>&1
    if not errorlevel 1 (
        echo  [frontend] Ready
        goto :frontend_ok
    )
)
echo  [frontend] Started (server check timed out -- may still be building)
:frontend_ok

echo.
echo  ========================================
echo    All services are running!
echo.
echo    Backend   http://localhost:%BACKEND_PORT%
echo    Frontend  http://localhost:%FRONTEND_PORT%
echo.
echo    To stop:  stop.bat
echo    Logs:     workspace\logs\
echo  ========================================
echo.
