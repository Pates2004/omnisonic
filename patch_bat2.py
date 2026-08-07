import io
import re

python_check_block_bilingual = """
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Warning, Python is missing on your system!
    echo Press ENTER to open the download page or ESCAPE to cancel.
    echo.
    echo [BLAD] Uwaga, w twoim systemie brakuje Pythona!
    echo Wcisnij ENTER, by otworzyc strone jego pobierania lub ESCAPE, by anulowac.
    powershell -NoProfile -Command "while(1){$k=[System.Console]::ReadKey(1); if($k.Key -eq 'Enter'){Start-Process 'https://www.python.org/downloads/'; exit 1} elseif($k.Key -eq 'Escape'){exit 0}}"
    exit /b
)
"""

def patch_file(filename):
    with io.open(filename, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Remove old block if exists
    if "brakuje Pythona" in content:
        # We need to replace the old block with the new one
        # Let's just find everything between IF %ERRORLEVEL% NEQ 0 ( and exit /b \n)
        
        # Regex to replace the whole block
        # Actually it's easier to just do a string replacement of the exact old text
        old_block = """
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Uwaga, w twoim systemie brakuje Pythona!
    echo Wcisnij ENTER, by otworzyc strone jego pobierania lub ESCAPE, by anulowac.
    powershell -NoProfile -Command "while(1){$k=[System.Console]::ReadKey(1); if($k.Key -eq 'Enter'){Start-Process 'https://www.python.org/downloads/'; exit 1} elseif($k.Key -eq 'Escape'){exit 0}}"
    exit /b
)
"""
        content = content.replace(old_block, python_check_block_bilingual)
        with io.open(filename, "w", encoding="utf-8", newline="") as f:
            f.write(content)

patch_file("start_desktop.bat")
patch_file("start.bat")
