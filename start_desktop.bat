@echo off
setlocal
title OmniSonic
color 0b

cd /d "%~dp0"

if not exist "desktop_launcher.ps1" (
    echo [ERROR] Missing desktop_launcher.ps1.
    echo [ERROR] Brakuje pliku desktop_launcher.ps1.
    pause
    exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop_launcher.ps1" %*
set "LAUNCHER_EXIT=%ERRORLEVEL%"

if not "%LAUNCHER_EXIT%"=="0" (
    echo.
    echo [ERROR] OmniSonic launcher failed with code %LAUNCHER_EXIT%.
    echo [ERROR] Launcher OmniSonic zakonczyl sie bledem %LAUNCHER_EXIT%.
    pause
)

exit /b %LAUNCHER_EXIT%
