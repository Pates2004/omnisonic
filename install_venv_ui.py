import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import subprocess
import threading
import sys
import os

def install_venv():
    root = tk.Tk()
    root.withdraw()
    
    if not messagebox.askokcancel("Uwaga - Omnisonic", "Nie wykryto środowiska (venv).\nCzy chcesz pobrać i zainstalować je teraz?"):
        sys.exit(1)
        
    prog_win = tk.Toplevel(root)
    prog_win.title("Trwa instalacja środowiska...")
    prog_win.geometry("400x120")
    
    # Center on screen
    prog_win.update_idletasks()
    width = prog_win.winfo_width()
    height = prog_win.winfo_height()
    x = (prog_win.winfo_screenwidth() // 2) - (width // 2)
    y = (prog_win.winfo_screenheight() // 2) - (height // 2)
    prog_win.geometry('{}x{}+{}+{}'.format(width, height, x, y))
    
    lbl = tk.Label(prog_win, text="Trwa pobieranie i instalacja, to może potrwać kilka minut...")
    lbl.pack(pady=10)
    
    progress = ttk.Progressbar(prog_win, mode='indeterminate', length=350)
    progress.pack(pady=5)
    progress.start(10)
    
    btn_cancel = tk.Button(prog_win, text="Anuluj")
    btn_cancel.pack(pady=5)
    
    cancel_flag = False
    proc = None
    
    def do_cancel():
        nonlocal cancel_flag
        if messagebox.askyesno("Uwaga", "Czy na pewno chcesz przerwać instalację?"):
            cancel_flag = True
            if proc:
                try:
                    proc.kill()
                except:
                    pass
            sys.exit(1)
            
    btn_cancel.config(command=do_cancel)
    prog_win.protocol("WM_DELETE_WINDOW", do_cancel)
    
    def worker():
        nonlocal proc
        commands = [
            ("Tworzenie wirtualnego środowiska...", f'"{sys.executable}" -m venv venv'),
            ("Aktualizacja pip...", r"venv\Scripts\python.exe -m pip install --upgrade pip"),
            ("Pobieranie PyTorch...", r"venv\Scripts\python.exe -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128"),
            ("Instalacja Omnisonic...", r"venv\Scripts\python.exe -m pip install -e ."),
            ("Pobieranie bibliotek graficznych...", r"venv\Scripts\python.exe -m pip install wxPython sounddevice soundfile numpy")
        ]
        
        for name, cmd in commands:
            if cancel_flag: return
            lbl.config(text=name)
            try:
                proc = subprocess.Popen(cmd, shell=True)
                proc.wait()
            except Exception as e:
                pass
                
        if not cancel_flag:
            prog_win.destroy()
            messagebox.showinfo("Gotowe", "Instalacja środowiska zakończona pomyślnie!\nWciśnij OK, aby uruchomić program.")
            root.destroy()
            
    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()

if __name__ == "__main__":
    if not os.path.exists("venv"):
        install_venv()
