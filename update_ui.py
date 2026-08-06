import codecs
import re

with codecs.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# 2. Add 'resume' logic to TogglePlayFile
toggle_old = """    def TogglePlayFile(self, btn_play, btn_stop, path_ctrl):
        path = path_ctrl.GetValue().strip()
        import time
        if btn_play.GetLabel() == self._("play_ref"):"""
        
toggle_new = """    def TogglePlayFile(self, btn_play, btn_stop, path_ctrl):
        path = path_ctrl.GetValue().strip()
        import time
        if btn_play.GetLabel() in [self._("play_ref"), self._("resume")]:"""
        
code = code.replace(toggle_old, toggle_new)

toggle_pause_old = """            btn_play.SetLabel("Pauza" if self.cfg.get("language", "pl") == "pl" else "Pause")
            btn_stop.Enable()"""
            
toggle_pause_new = """            btn_play.SetLabel(self._("pause"))
            btn_stop.Enable()"""
code = code.replace(toggle_pause_old, toggle_pause_new)

code = re.sub(r'(elapsed = time\.time\(\) - state\[\'start_time\'\]\s+state\[\'offset\'\] \+= int\(elapsed \* state\[\'fs\'\]\)\s+)btn_play\.SetLabel\(self\._\("play_ref"\)\)', r'\1btn_play.SetLabel(self._("resume"))', code)

# 3. Add 'resume' logic to OnPlayAudio
onplay_old = """    def OnPlayAudio(self, event):
        import time
        if self.btn_play.GetLabel() == self._("play"):"""
        
onplay_new = """    def OnPlayAudio(self, event):
        import time
        if self.btn_play.GetLabel() in [self._("play"), self._("resume")]:"""
code = code.replace(onplay_old, onplay_new)

onplay_pause_old = """            self.btn_play.SetLabel("Pauza" if self.cfg.get("language", "pl") == "pl" else "Pause")
            self.btn_stop.Enable()"""
onplay_pause_new = """            self.btn_play.SetLabel(self._("pause"))
            self.btn_stop.Enable()"""
code = code.replace(onplay_pause_old, onplay_pause_new)

code = re.sub(r'(elapsed = time\.time\(\) - self\.gen_play_start\s+self\.gen_play_offset \+= int\(elapsed \* self\.sample_rate\)\s+)self\.btn_play\.SetLabel\(self\._\("play"\)\)', r'\1self.btn_play.SetLabel(self._("resume"))', code)

# 4. Add Record buttons (Save, Delete) in Clone Tab
clone_btns_old = """        self.btn_rec_ref = wx.Button(tab, label=self._("rec_ref"))
        self.btn_rec_ref.Bind(wx.EVT_BUTTON, lambda e: self.ToggleRecord(self.btn_rec_ref, self.clone_ref_audio))
        
        hbox_ref.Add(self.clone_ref_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(btn_browse, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_play_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_stop_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_rec_ref, 0, wx.EXPAND, 0)"""
        
clone_btns_new = """        self.btn_rec_ref = wx.Button(tab, label=self._("rec_ref"))
        self.btn_save_rec_ref = wx.Button(tab, label=self._("save"))
        self.btn_del_rec_ref = wx.Button(tab, label=self._("delete"))
        self.btn_save_rec_ref.Disable()
        self.btn_del_rec_ref.Disable()
        self.btn_rec_ref.Bind(wx.EVT_BUTTON, lambda e: self.ToggleRecord(self.btn_rec_ref, self.clone_ref_audio, self.btn_save_rec_ref, self.btn_del_rec_ref))
        self.btn_save_rec_ref.Bind(wx.EVT_BUTTON, lambda e: self.OnSaveRec(self.clone_ref_audio))
        self.btn_del_rec_ref.Bind(wx.EVT_BUTTON, lambda e: self.OnDelRec(self.clone_ref_audio, self.btn_save_rec_ref, self.btn_del_rec_ref))
        
        hbox_ref.Add(self.clone_ref_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(btn_browse, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_play_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_stop_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_rec_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_save_rec_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_del_rec_ref, 0, wx.EXPAND, 0)"""
code = code.replace(clone_btns_old, clone_btns_new)

# 5. Add Record buttons (Save, Delete) in Preset Tab
preset_btns_old = """        self.btn_rec_preset = wx.Button(tab, label=self._("rec_ref"))
        self.btn_rec_preset.Bind(wx.EVT_BUTTON, lambda e: self.ToggleRecord(self.btn_rec_preset, self.preset_audio))
        
        hbox1.Add(self.preset_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(btn_br, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_play_preset, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_stop_preset, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_rec_preset, 0, wx.EXPAND, 0)"""

preset_btns_new = """        self.btn_rec_preset = wx.Button(tab, label=self._("rec_ref"))
        self.btn_save_rec_pre = wx.Button(tab, label=self._("save"))
        self.btn_del_rec_pre = wx.Button(tab, label=self._("delete"))
        self.btn_save_rec_pre.Disable()
        self.btn_del_rec_pre.Disable()
        self.btn_rec_preset.Bind(wx.EVT_BUTTON, lambda e: self.ToggleRecord(self.btn_rec_preset, self.preset_audio, self.btn_save_rec_pre, self.btn_del_rec_pre))
        self.btn_save_rec_pre.Bind(wx.EVT_BUTTON, lambda e: self.OnSaveRec(self.preset_audio))
        self.btn_del_rec_pre.Bind(wx.EVT_BUTTON, lambda e: self.OnDelRec(self.preset_audio, self.btn_save_rec_pre, self.btn_del_rec_pre))
        
        hbox1.Add(self.preset_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(btn_br, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_play_preset, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_stop_preset, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_rec_preset, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_save_rec_pre, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_del_rec_pre, 0, wx.EXPAND, 0)"""
code = code.replace(preset_btns_old, preset_btns_new)

# 6. Update ToggleRecord and add OnSaveRec / OnDelRec
togglerec_old = """    def ToggleRecord(self, btn, path_ctrl):
        if btn.GetLabel() == self._("rec_ref"):
            btn.SetLabel(self._("stop_rec"))
            self.rec_data = []
            self.rec_fs = 24000
            
            def callback(indata, frames, time, status):
                self.rec_data.append(indata.copy())
                
            self.rec_stream = sd.InputStream(samplerate=self.rec_fs, channels=1, callback=callback)
            self.rec_stream.start()
        else:
            btn.SetLabel(self._("rec_ref"))
            if hasattr(self, 'rec_stream'):
                self.rec_stream.stop()
                self.rec_stream.close()
                if self.rec_data:
                    audio = np.concatenate(self.rec_data)
                    sf.write("recorded_ref.wav", audio, self.rec_fs)
                    path_ctrl.SetValue(os.path.abspath("recorded_ref.wav"))"""
                    
togglerec_new = """    def ToggleRecord(self, btn, path_ctrl, btn_save=None, btn_del=None):
        if btn.GetLabel() == self._("rec_ref"):
            btn.SetLabel(self._("stop_rec"))
            self.rec_data = []
            self.rec_fs = 24000
            
            def callback(indata, frames, time, status):
                self.rec_data.append(indata.copy())
                
            self.rec_stream = sd.InputStream(samplerate=self.rec_fs, channels=1, callback=callback)
            self.rec_stream.start()
        else:
            btn.SetLabel(self._("rec_ref"))
            if hasattr(self, 'rec_stream'):
                self.rec_stream.stop()
                self.rec_stream.close()
                if self.rec_data:
                    audio = np.concatenate(self.rec_data)
                    sf.write("recorded_ref.wav", audio, self.rec_fs)
                    path_ctrl.SetValue(os.path.abspath("recorded_ref.wav"))
                    if btn_save: btn_save.Enable()
                    if btn_del: btn_del.Enable()
                    
    def OnSaveRec(self, path_ctrl):
        path = path_ctrl.GetValue().strip()
        if not os.path.exists(path): return
        with wx.FileDialog(self, self._("save"), wildcard="WAV (*.wav)|*.wav", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fd:
            if fd.ShowModal() != wx.ID_CANCEL:
                import shutil
                shutil.copy2(path, fd.GetPath())
                wx.MessageBox(self._("gen_success_msg"), self._("success_title"), wx.OK | wx.ICON_INFORMATION)
                
    def OnDelRec(self, path_ctrl, btn_save, btn_del):
        path = path_ctrl.GetValue().strip()
        msg = "Czy na pewno chcesz usunąć nagranie z mikrofonu?" if self.cfg.get("language", "pl") == "pl" else "Are you sure you want to delete the microphone recording?"
        dlg = wx.MessageDialog(self, msg, self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            path_ctrl.SetValue("")
            btn_save.Disable()
            btn_del.Disable()
            if os.path.exists(path) and "recorded_ref.wav" in path:
                try: os.remove(path)
                except: pass"""
code = code.replace(togglerec_old, togglerec_new)

# 7. Add Checkboxes for Notifications in SettingsDialog
chk_notify_old = """            self.chk_confirm_success = wx.CheckBox(tab_opts, label=self._("confirm_success_lbl"))
            self.chk_confirm_success.SetValue(self.cfg.get("confirm_success", False))
            vbox_opts.Add(self.chk_confirm_success, 0, wx.ALL | wx.EXPAND, 5)"""
            
chk_notify_new = """            self.chk_confirm_success = wx.CheckBox(tab_opts, label=self._("confirm_success_lbl"))
            self.chk_confirm_success.SetValue(self.cfg.get("confirm_success", False))
            vbox_opts.Add(self.chk_confirm_success, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_notify_sys = wx.CheckBox(tab_opts, label=self._("notify_sys_lbl"))
            self.chk_notify_sys.SetValue(self.cfg.get("notify_system", True))
            vbox_opts.Add(self.chk_notify_sys, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_notify_pop = wx.CheckBox(tab_opts, label=self._("notify_pop_lbl"))
            self.chk_notify_pop.SetValue(self.cfg.get("notify_popup", False))
            vbox_opts.Add(self.chk_notify_pop, 0, wx.ALL | wx.EXPAND, 5)"""
code = code.replace(chk_notify_old, chk_notify_new)

# 8. Save checkboxes in SettingsDialog
cfg_notify_old = """            self.cfg["warn_exit"] = self.chk_warn_exit.GetValue()
            self.cfg["confirm_success"] = self.chk_confirm_success.GetValue()"""
cfg_notify_new = """            self.cfg["warn_exit"] = self.chk_warn_exit.GetValue()
            self.cfg["confirm_success"] = self.chk_confirm_success.GetValue()
            self.cfg["notify_system"] = self.chk_notify_sys.GetValue()
            self.cfg["notify_popup"] = self.chk_notify_pop.GetValue()"""
code = code.replace(cfg_notify_old, cfg_notify_new)

with codecs.open("wx_app.py", "w", encoding="utf-8") as f:
    f.write(code)
