import json
import codecs

pl_strings = {
    "norm_text_lbl": "Normalizuj tekst (zamienia 123 na słowa)",
    "asr_model_lbl": "Model Whisper (rozpoznawanie mowy):",
    "auto_voice": "Losowy Głos",
    "auto_text_lbl": "Tekst:",
    "auto_lang_lbl": "Język:",
    "btn_gen_auto": "Generuj (Losowy głos)",
    "op_auto_msg": "Trwa generowanie losowego głosu...",
    "op_auto_title": "Generowanie",
    "duration_lbl": "Wymuś czas (Duration) w sekundach:",
    "menu_tags": "Tagi i Symbole",
    "menu_tags_help": "Wyświetl dostępne tagi mowy",
    "menu_help": "Pomoc",
    "title_tags": "Dostępne Tagi",
    "msg_tags": "Dostępne specjalne tagi do wpisania w treść tekstu:\n\nEmocje / dźwięki:\n[laughter] - Śmiech\n[sigh] - Westchnienie\n\nWykrzyknienia / pytania (najlepiej działają z ang):\n[confirmation-en] - Potwierdzenie\n[question-en] - Pytanie ogólne\n[question-ah] - Zdziwienie (Ah?)\n[question-oh] - Zdziwienie (Oh?)\n[question-ei] - Zdziwienie (Ei?)\n[question-yi] - Zdziwienie (Yi?)\n[surprise-ah] - Niespodzianka (Ah!)\n[surprise-oh] - Niespodzianka (Oh!)\n[surprise-wa] - Niespodzianka (Wa!)\n[surprise-yo] - Niespodzianka (Yo!)\n[dissatisfaction-hnn] - Niezadowolenie (Hnn...)\n\nCMU Dict (tylko angielski):\nMożesz wpisać fonemy w nawiasach klamrowych, np. [B EY1 S].",
    "msg_dl_model": "Program za chwilę pobierze nowy model: {model}. Zależnie od połączenia może to potrwać parę minut.\n\nCzy chcesz kontynuować?",
    "title_dl_model": "Pobieranie modelu",
    "msg_dl_conn": "Trwa pobieranie modelu {model}...",
    "cancel_dl_prompt": "Czy na pewno chcesz anulować pobieranie modelu? Może to spowodować problemy z działaniem, jeśli anulujesz w trakcie weryfikacji.",
    "cancel_title": "Anulowanie pobierania"
}

en_strings = {
    "norm_text_lbl": "Normalize text (converts 123 to words)",
    "asr_model_lbl": "Whisper Model (speech recognition):",
    "auto_voice": "Random Voice",
    "auto_text_lbl": "Text:",
    "auto_lang_lbl": "Language:",
    "btn_gen_auto": "Generate (Random voice)",
    "op_auto_msg": "Generating random voice...",
    "op_auto_title": "Generating",
    "duration_lbl": "Force duration (seconds):",
    "menu_tags": "Tags and Symbols",
    "menu_tags_help": "Show available speech tags",
    "menu_help": "Help",
    "title_tags": "Available Tags",
    "msg_tags": "Available special tags to type into text:\n\nEmotions / sounds:\n[laughter] - Laughter\n[sigh] - Sigh\n\nExclamations / questions (works best with en):\n[confirmation-en]\n[question-en]\n[question-ah]\n[question-oh]\n[question-ei]\n[question-yi]\n[surprise-ah]\n[surprise-oh]\n[surprise-wa]\n[surprise-yo]\n[dissatisfaction-hnn]\n\nCMU Dict (English only):\nYou can type phonemes in braces, e.g. [B EY1 S].",
    "msg_dl_model": "The program will now download a new model: {model}. Depending on your connection, this may take a few minutes.\n\nDo you want to continue?",
    "title_dl_model": "Downloading model",
    "msg_dl_conn": "Downloading model {model}...",
    "cancel_dl_prompt": "Are you sure you want to cancel the model download? This may cause issues if canceled during verification.",
    "cancel_title": "Cancel download"
}

for lng_file, strings in [("langs/pl.lng", pl_strings), ("langs/en.lng", en_strings)]:
    with codecs.open(lng_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    for k, v in strings.items():
        data[k] = v
    with codecs.open(lng_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

with codecs.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Replace hardcoded text in wx_app.py
replaces = [
    ('label="Model Whisper (rozpoznawanie mowy):"', 'label=self._("asr_model_lbl")'),
    ('label=self._("norm_text_lbl") if hasattr(self, \'_"\') and self._("norm_text_lbl") != "norm_text_lbl" else "Normalizuj tekst (zamienia 123 na słowa)"', 'label=self._("norm_text_lbl")'),
    ('self._("auto_voice") if hasattr(self, \'_\') and self._("auto_voice") != "auto_voice" else "Auto Voice"', 'self._("auto_voice")'),
    ('label="Tekst:"', 'label=self._("auto_text_lbl")'),
    ('label="Język / Language:"', 'label=self._("auto_lang_lbl")'),
    ('label="Generuj (Losowy głos)"', 'label=self._("btn_gen_auto")'),
    ('"Generowanie", "Trwa generowanie losowego głosu..."', 'self._("op_auto_title"), self._("op_auto_msg")'),
    ('label="Wymuś czas (Duration) w sekundach:"', 'label=self._("duration_lbl")'),
    ('item_tags = help_menu.Append(wx.ID_ANY, "Tagi i Symbole (Tags/Symbols)", "Wyświetl dostępne tagi mowy")', 'item_tags = help_menu.Append(wx.ID_ANY, self._("menu_tags"), self._("menu_tags_help"))'),
    ('menubar.Append(help_menu, "Pomoc (Help)")', 'menubar.Append(help_menu, self._("menu_help"))'),
    ('label=self._("norm_text_lbl") if hasattr(self, \'_\') and self._("norm_text_lbl") != "norm_text_lbl" else "Normalizuj tekst (zamienia 123 na słowa)"', 'label=self._("norm_text_lbl")')
]

for old, new in replaces:
    code = code.replace(old, new)

# Replace hardcoded Tags messagebox
tags_old = """        msg = \"\"\"Dostępne specjalne tagi do wpisania w treść tekstu:

Emocje / dźwięki:
[laughter] - Śmiech
[sigh] - Westchnienie

Wykrzyknienia / pytania (najlepiej działają z ang):
[confirmation-en] - Potwierdzenie
[question-en] - Pytanie ogólne
[question-ah] - Zdziwienie (Ah?)
[question-oh] - Zdziwienie (Oh?)
[question-ei] - Zdziwienie (Ei?)
[question-yi] - Zdziwienie (Yi?)
[surprise-ah] - Niespodzianka (Ah!)
[surprise-oh] - Niespodzianka (Oh!)
[surprise-wa] - Niespodzianka (Wa!)
[surprise-yo] - Niespodzianka (Yo!)
[dissatisfaction-hnn] - Niezadowolenie (Hnn...)

CMU Dict (tylko angielski):
Możesz wpisać fonemy w nawiasach klamrowych, np. [B EY1 S].\"\"\"
        wx.MessageBox(msg, "Dostępne Tagi", wx.OK | wx.ICON_INFORMATION)"""
tags_new = """        wx.MessageBox(self._("msg_tags"), self._("title_tags"), wx.OK | wx.ICON_INFORMATION)"""
code = code.replace(tags_old, tags_new)

# Implement DownloadDialog
dl_dialog = """class DownloadDialog(wx.Dialog):
    def __init__(self, parent, title, label, repo_id, lang_func):
        super().__init__(parent, title=title, size=(400, 150))
        self._ = lang_func
        self.repo_id = repo_id
        
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.lbl = wx.StaticText(self, label=label)
        vbox.Add(self.lbl, 0, wx.ALL | wx.EXPAND, 10)
        
        self.gauge = wx.Gauge(self, range=100)
        vbox.Add(self.gauge, 0, wx.ALL | wx.EXPAND, 10)
        
        self.btn_cancel = wx.Button(self, label=self._("btn_cancel"))
        self.btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        vbox.Add(self.btn_cancel, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(vbox)
        self.Bind(wx.EVT_CLOSE, self.OnCancel)
        
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnTimer, self.timer)
        self.timer.Start(50)
        
        self.cancel_flag = False
        
        import threading
        self.t = threading.Thread(target=self._dl_worker)
        self.t.daemon = True
        self.t.start()

    def OnTimer(self, event):
        self.gauge.Pulse()
        if not self.t.is_alive() and not self.cancel_flag:
            self.EndModal(wx.ID_OK)

    def OnCancel(self, event):
        msg = self._("cancel_dl_prompt")
        title = self._("cancel_title")
        if wx.MessageBox(msg, title, wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.cancel_flag = True
            self.timer.Stop()
            self.EndModal(wx.ID_CANCEL)

    def _dl_worker(self):
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=self.repo_id)
        except Exception as e:
            wx.CallAfter(wx.MessageBox, str(e), "Error", wx.OK | wx.ICON_ERROR)

class SettingsDialog(wx.Dialog):"""

code = code.replace("class SettingsDialog(wx.Dialog):", dl_dialog)

# Update the download logic in OnSave
save_dl_old = """            if new_asr != self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo"):
                import wx
                msg = f"Program za chwilę pobierze nowy model: {new_asr}. Zależnie od połączenia może to potrwać parę minut.\n\nCzy chcesz kontynuować?"
                if wx.MessageBox(msg, "Pobieranie modelu", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                    dlg = wx.ProgressDialog("Pobieranie", "Łączenie z HuggingFace...", maximum=100, parent=self, style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_CAN_ABORT)
                    
                    import threading
                    def _dl():
                        try:
                            from huggingface_hub import snapshot_download
                            snapshot_download(repo_id=new_asr)
                            wx.CallAfter(lambda: dlg.Update(100, "Gotowe") if dlg else None)
                        except Exception as e:
                            wx.CallAfter(wx.MessageBox, f"Błąd pobierania: {str(e)}", "Błąd", wx.OK | wx.ICON_ERROR)
                            wx.CallAfter(lambda: dlg.Update(100, "Błąd") if dlg else None)

                    t = threading.Thread(target=_dl)
                    t.daemon = True
                    t.start()
                    
                    import time
                    while t.is_alive():
                        wx.Yield()
                        cont, skip = dlg.Pulse(f"Trwa pobieranie modelu {new_asr}...")
                        if not cont:
                            break
                        time.sleep(0.05)
                        
                    try:
                        dlg.Destroy()
                    except:
                        pass
                else:
                    return # Przerwij zapisywanie"""
                    
save_dl_new = """            if new_asr != self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo"):
                msg = self._("msg_dl_model").format(model=new_asr)
                title = self._("title_dl_model")
                if wx.MessageBox(msg, title, wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                    dlg_lbl = self._("msg_dl_conn").format(model=new_asr)
                    dlg = DownloadDialog(self, title, dlg_lbl, new_asr, self._)
                    res = dlg.ShowModal()
                    dlg.Destroy()
                    if res == wx.ID_CANCEL:
                        return # User cancelled
                else:
                    return # User clicked NO"""

code = code.replace(save_dl_old, save_dl_new)

with codecs.open("wx_app.py", "w", encoding="utf-8") as f:
    f.write(code)
