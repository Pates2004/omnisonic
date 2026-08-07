import io

python_check_block = """
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Uwaga, w twoim systemie brakuje Pythona!
    echo Wcisnij ENTER, by otworzyc strone jego pobierania lub ESCAPE, by anulowac.
    powershell -NoProfile -Command "while(1){$k=[System.Console]::ReadKey(1); if($k.Key -eq 'Enter'){Start-Process 'https://www.python.org/downloads/'; exit 1} elseif($k.Key -eq 'Escape'){exit 0}}"
    exit /b
)
"""

def patch_file(filename):
    with io.open(filename, "r", encoding="utf-8") as f:
        content = f.read()
    
    if "brakuje Pythona" not in content:
        # Insert after cd /d "%~dp0"
        parts = content.split('cd /d "%~dp0"\n')
        if len(parts) == 2:
            new_content = parts[0] + 'cd /d "%~dp0"\n' + python_check_block + parts[1]
            with io.open(filename, "w", encoding="utf-8", newline="") as f:
                f.write(new_content)

patch_file("start_desktop.bat")
patch_file("start.bat")
