@echo off
setlocal EnableExtensions DisableDelayedExpansion
title OmniSonic
color 0b

cd /d "%~dp0"

if not exist "desktop_launcher.ps1" (
    echo [ERROR] Missing desktop_launcher.ps1.
    echo [ERROR] Brakuje pliku desktop_launcher.ps1.
    pause
    exit /b 1
)

if not "%~1"=="" goto visible_launch
set "OMNISONIC_LAUNCH_STYLE="
for /f "delims=" %%H in ('powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop_launcher.ps1" -QueryHiddenLaunch') do set "OMNISONIC_LAUNCH_STYLE=%%H"
if /i not "%OMNISONIC_LAUNCH_STYLE%"=="HIDE" goto visible_launch
start "" powershell.exe -NoLogo -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0desktop_launcher.ps1"
if not errorlevel 1 exit /b 0

:visible_launch

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop_launcher.ps1" %*
set "LAUNCHER_EXIT=%ERRORLEVEL%"

if not "%LAUNCHER_EXIT%"=="0" (
    echo.
    echo [ERROR] OmniSonic launcher failed with code %LAUNCHER_EXIT%.
    echo [ERROR] Launcher OmniSonic zakonczyl sie bledem %LAUNCHER_EXIT%.
    pause
)

exit /b %LAUNCHER_EXIT%
