@echo off
setlocal EnableExtensions DisableDelayedExpansion
title OmniSonic Power Switch
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0power_switch.ps1" %*
set "SWITCH_EXIT=%ERRORLEVEL%"
if not "%SWITCH_EXIT%"=="0" echo [ERROR] Power Switch failed. Your backup has not been deleted.
if "%~1"=="" pause
exit /b %SWITCH_EXIT%
