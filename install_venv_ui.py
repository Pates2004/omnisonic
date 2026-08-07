import tkinter as tk
from tkinter import messagebox
import subprocess
import sys
import os

def install_venv():
    root = tk.Tk()
    root.withdraw()
    
    if not messagebox.askokcancel("Uwaga - Omnisonic", "Nie wykryto środowiska (venv).\nZostanie pobrany moduł instalatora (wxPython), po czym wyświetli się główny instalator.\nCzy chcesz pobrać i zainstalować je teraz?"):
        sys.exit(1)
        
    prog_win = tk.Toplevel(root)
    prog_win.title("Pobieranie instalatora...")
    prog_win.geometry("400x100")
    
    prog_win.update_idletasks()
    width = prog_win.winfo_width()
    height = prog_win.winfo_height()
    x = (prog_win.winfo_screenwidth() // 2) - (width // 2)
    y = (prog_win.winfo_screenheight() // 2) - (height // 2)
    prog_win.geometry('{}x{}+{}+{}'.format(width, height, x, y))
    
    lbl = tk.Label(prog_win, text="Trwa tworzenie środowiska i pobieranie instalatora...\nProszę czekać, może to zająć kilka minut.", justify=tk.CENTER)
    lbl.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)
    
    prog_win.update()
    
    try:
        if not os.path.exists("venv"):
            subprocess.run(f'"{sys.executable}" -m venv venv', shell=True, check=True)
            
        pip_path = os.path.join("venv", "Scripts", "python.exe")
        subprocess.run(f'"{pip_path}" -m pip install --upgrade pip', shell=True, check=True)
        subprocess.run(f'"{pip_path}" -m pip install wxPython', shell=True, check=True)
        
    except Exception as e:
        prog_win.destroy()
        messagebox.showerror("Błąd", f"Nie udało się zainstalować środowiska bazowego:\n{e}")
        root.destroy()
        sys.exit(1)
        
    prog_win.destroy()
    root.destroy()
    
    # Uruchamiamy instalator w wxPython korzystając ze środowiska venv
    wx_script = "install_venv_ui_wx.py"
    if os.path.exists(wx_script):
        ret = subprocess.call(f'"{pip_path}" {wx_script}', shell=True)
        sys.exit(ret)
    else:
        sys.exit(0)

if __name__ == "__main__":
    if not os.path.exists("venv"):
        install_venv()
