@echo off
REM stop.bat -- network_agent stop (Windows)
REM
REM Stops the backend (port 8010) and frontend (port 5173) processes.
REM
REM Usage:
REM   stop.bat         Stop all network_agent services

setlocal

echo.
echo  ========================================
echo    Stopping network_agent ...
echo  ========================================
echo.

REM Kill backend
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8010 " ^| findstr "LISTENING"') do (
    set "FOUND=1"
    taskkill /F /PID %%a >nul 2>&1
)
if "%FOUND%"=="1" (echo  [backend]  Stopped) else (echo  [backend]  Not running)

REM Kill frontend
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173 " ^| findstr "LISTENING"') do (
    set "FOUND=1"
    taskkill /F /PID %%a >nul 2>&1
)
if "%FOUND%"=="1" (echo  [frontend] Stopped) else (echo  [frontend] Not running)

echo.
echo  ========================================
echo    Done.
echo  ========================================
echo.
pause
