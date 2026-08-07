import io

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()
    
# Import huggingface_hub is_model_cached logic at top or within the method
# I will just write a helper in SettingsDialog or globally.

helper = """
def is_model_cached(repo_id):
    try:
        import os
        from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE
        path = os.path.join(HUGGINGFACE_HUB_CACHE, "models--" + repo_id.replace("/", "--"))
        return os.path.exists(path)
    except:
        return False
"""

if "def is_model_cached" not in code:
    code = code.replace("class SettingsDialog", helper + "\nclass SettingsDialog")
    
# Find where to add cb_asr in tab_sys
old_sys = """            vbox_sys.Add(self.cb_preset_disp, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_clean_temp = wx.CheckBox(tab_sys, label=self._("clean_temp_lbl"))"""

new_sys = """            vbox_sys.Add(self.cb_preset_disp, 0, wx.ALL | wx.EXPAND, 5)
            
            wx.StaticText(tab_sys, label=self._("asr_model_lbl"))
            self.cb_asr = wx.ComboBox(tab_sys, choices=[
                "openai/whisper-large-v3-turbo",
                "openai/whisper-large-v3",
                "openai/whisper-medium",
                "openai/whisper-small",
                "openai/whisper-base",
                "openai/whisper-tiny"
            ], style=wx.CB_READONLY)
            self.cb_asr.SetName(self._("asr_model_lbl"))
            cur_asr = self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo")
            if cur_asr in self.cb_asr.GetStrings():
                self.cb_asr.SetValue(cur_asr)
            else:
                self.cb_asr.SetValue("openai/whisper-large-v3-turbo")
            vbox_sys.Add(self.cb_asr, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_clean_temp = wx.CheckBox(tab_sys, label=self._("clean_temp_lbl"))"""

if "self.cb_asr =" not in code:
    code = code.replace(old_sys, new_sys)
    
# Update OnSave to check if it's cached
old_save = """        if not self.is_first_run:
            self.cfg["show_console"] = self.chk_console.GetValue()"""

new_save = """        if not self.is_first_run:
            new_asr = self.cb_asr.GetValue()
            if new_asr != self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo"):
                if new_asr != "openai/whisper-large-v3-turbo" and not is_model_cached(new_asr):
                    msg = self._("dl_model_prompt") if "dl_model_prompt" in LOCALE.get(self.lang, {}) else f"Wybrany model {new_asr} nie jest pobrany. Czy chcesz go pobrać i zainstalować teraz?"
                    title = self._("dl_title") if "dl_title" in LOCALE.get(self.lang, {}) else "Pobieranie modelu"
                    if wx.MessageBox(msg, title, wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                        dlg = DownloadDialog(self, title, f"Pobieranie {new_asr}...", new_asr, self._)
                        if dlg.ShowModal() == wx.ID_OK:
                            self.cfg["asr_model_name"] = new_asr
                        else:
                            self.cb_asr.SetValue(self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo"))
                            return # Cancel save
                    else:
                        self.cb_asr.SetValue(self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo"))
                        return # Cancel save
                else:
                    self.cfg["asr_model_name"] = new_asr

            self.cfg["show_console"] = self.chk_console.GetValue()"""

if "new_asr = self.cb_asr.GetValue()" not in code:
    code = code.replace(old_save, new_save)
    
with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
