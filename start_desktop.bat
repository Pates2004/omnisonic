@echo off
title Omnisonic Console View
color 0b

echo ===================================================
echo               Omnisonic Console View
echo ===================================================
echo.

cd /d "%~dp0"

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Uwaga, w twoim systemie brakuje Pythona!
    echo Wcisnij ENTER, by otworzyc strone jego pobierania lub ESCAPE, by anulowac.
    powershell -NoProfile -Command "while(1){$k=[System.Console]::ReadKey(1); if($k.Key -eq 'Enter'){Start-Process 'https://www.python.org/downloads/'; exit 1} elseif($k.Key -eq 'Escape'){exit 0}}"
    exit /b
)

IF NOT EXIST venv (
    echo [INFO] Environment not found. Launching installer UI...
    python install_venv_ui.py
    IF %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Installation cancelled.
        exit /b
    )
)

echo [INFO] Activating Virtual Environment...
call venv\Scripts\activate.bat

python -c "import json, sys, os; sys.exit(0 if (os.path.exists('settings.json') and json.load(open('settings.json', encoding='utf-8')).get('validate_components', False)) else 1)" 2>nul
IF %ERRORLEVEL% EQU 0 (
    echo [INFO] Walidacja komponentow wlaczona. Trwa sprawdzanie instalacji pip...
    pip install wxPython sounddevice soundfile numpy
) ELSE (
    python -c "import wx, sounddevice, soundfile" 2>nul
    IF %ERRORLEVEL% NEQ 0 (
        echo [INFO] Brakuje bibliotek desktopowych. Trwa doinstalowywanie...
        pip install wxPython sounddevice soundfile numpy
    )
)

echo [INFO] Launching Omnisonic Desktop App...
python wx_app.py

python -c "import json, sys, os; d = json.load(open('settings.json', encoding='utf-8')) if os.path.exists('settings.json') else {}; sys.exit(1 if d.get('show_console', False) and not d.get('close_console_on_exit', True) else 0)" 2>nul
IF %ERRORLEVEL% NEQ 0 (
    echo [INFO] Program zakończony. Zamykanie konsoli zostało anulowane w ustawieniach.
    pause
) ELSE (
    exit
)
