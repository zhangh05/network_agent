@echo off
setlocal EnableExtensions
title Network Agent

set "ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%start.ps1" %*
set "STATUS=%ERRORLEVEL%"

if not "%CI%"=="true" if not "%NETWORK_AGENT_NO_PAUSE%"=="1" pause
exit /b %STATUS%
