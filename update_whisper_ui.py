import codecs

with codecs.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

settings_old = """            wx.StaticText(tab_opts, label="Model Whisper (zostaw puste dla domyślnego openai/whisper-large-v3-turbo):")
            self.tc_asr_model = wx.TextCtrl(tab_opts, value=self.cfg.get("asr_model_name", ""))
            vbox_opts.Add(self.tc_asr_model, 0, wx.ALL | wx.EXPAND, 5)"""

settings_new = """            wx.StaticText(tab_opts, label="Model Whisper (rozpoznawanie mowy):")
            choices_asr = [
                "openai/whisper-large-v3-turbo",
                "openai/whisper-large-v3",
                "openai/whisper-large-v2",
                "openai/whisper-medium",
                "openai/whisper-small",
                "openai/whisper-base",
                "openai/whisper-tiny"
            ]
            self.cb_asr_model = wx.ComboBox(tab_opts, choices=choices_asr, style=wx.CB_DROPDOWN)
            self.cb_asr_model.SetValue(self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo"))
            vbox_opts.Add(self.cb_asr_model, 0, wx.ALL | wx.EXPAND, 5)"""

code = code.replace(settings_old, settings_new)

save_cfg_old = """            self.cfg["normalize_text"] = self.chk_norm_text.GetValue()
            self.cfg["asr_model_name"] = self.tc_asr_model.GetValue().strip()"""

save_cfg_new = """            self.cfg["normalize_text"] = self.chk_norm_text.GetValue()
            
            new_asr = self.cb_asr_model.GetValue().strip()
            if not new_asr: new_asr = "openai/whisper-large-v3-turbo"
            
            if new_asr != self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo"):
                import wx
                msg = f"Program za chwilę pobierze nowy model: {new_asr}. Zależnie od połączenia może to potrwać parę minut.\\n\\nCzy chcesz kontynuować?"
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
                    return # Przerwij zapisywanie
                    
            self.cfg["asr_model_name"] = new_asr"""

code = code.replace(save_cfg_old, save_cfg_new)

with codecs.open("wx_app.py", "w", encoding="utf-8") as f:
    f.write(code)
