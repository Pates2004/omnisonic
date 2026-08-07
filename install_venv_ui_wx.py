import wx
import subprocess
import threading
import sys
import os

class InstallDialog(wx.Dialog):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, size=(450, 180))
        self.cancel_flag = False
        self.proc = None
        
        self.InitUI()
        self.Centre()
        
    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        self.lbl = wx.StaticText(panel, label="Trwa pobieranie i instalacja środowiska...\nMoże to potrwać dłuższą chwilę.")
        vbox.Add(self.lbl, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 15)
        
        self.gauge = wx.Gauge(panel, range=100, style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)
        vbox.Add(self.gauge, 0, wx.ALL | wx.EXPAND, 10)
        
        self.btn_cancel = wx.Button(panel, label="Anuluj")
        self.btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        vbox.Add(self.btn_cancel, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 5)
        
        panel.SetSizer(vbox)
        self.Bind(wx.EVT_CLOSE, self.OnCancel)
        
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnTimer, self.timer)
        self.timer.Start(50)
        
        self.worker_thread = threading.Thread(target=self.Worker, daemon=True)
        self.worker_thread.start()
        
    def OnTimer(self, event):
        self.gauge.Pulse()
        if not self.worker_thread.is_alive():
            self.timer.Stop()
            self.EndModal(wx.ID_OK)
            
    def OnCancel(self, event):
        dlg = wx.MessageDialog(self, "Czy na pewno chcesz przerwać instalację?\nMoże to uszkodzić środowisko.", "Uwaga", wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            self.cancel_flag = True
            if self.proc:
                try:
                    self.proc.kill()
                except:
                    pass
            self.timer.Stop()
            self.EndModal(wx.ID_CANCEL)
        else:
            if isinstance(event, wx.CloseEvent):
                event.Veto()
                
    def Worker(self):
        commands = [
            ("Pobieranie PyTorch...", r"venv\Scripts\python.exe -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128"),
            ("Instalacja Omnisonic...", r"venv\Scripts\python.exe -m pip install -e ."),
            ("Pobieranie bibliotek graficznych...", r"venv\Scripts\python.exe -m pip install sounddevice soundfile numpy")
        ]
        
        for name, cmd in commands:
            if self.cancel_flag: return
            wx.CallAfter(self.lbl.SetLabel, name)
            try:
                self.proc = subprocess.Popen(cmd, shell=True)
                self.proc.wait()
            except Exception as e:
                pass
                
        if not self.cancel_flag:
            wx.CallAfter(wx.MessageBox, "Instalacja środowiska zakończona pomyślnie!\nWciśnij OK, aby uruchomić program.", "Gotowe", wx.OK | wx.ICON_INFORMATION)

if __name__ == "__main__":
    app = wx.App(False)
    dlg = InstallDialog(None, "Instalacja środowiska Omnisonic")
    res = dlg.ShowModal()
    dlg.Destroy()
    
    if res == wx.ID_CANCEL:
        sys.exit(1)
    else:
        sys.exit(0)
