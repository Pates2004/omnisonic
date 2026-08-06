import re
import codecs

with codecs.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update generated audio buttons in InitUI
gen_audio_old = """        self.btn_play = wx.Button(self.panel, label=self._("play"))
        self.btn_play.Bind(wx.EVT_BUTTON, self.OnPlayAudio)
        self.btn_play.Disable()
        
        self.btn_save = wx.Button(self.panel, label=self._("save"))
        self.btn_save.Bind(wx.EVT_BUTTON, self.OnSaveAudio)
        self.btn_save.Disable()
        
        hbox_audio.Add(self.btn_play, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_audio.Add(self.btn_save, 1, wx.EXPAND, 0)"""

gen_audio_new = """        self.btn_play = wx.Button(self.panel, label=self._("play"))
        self.btn_play.Bind(wx.EVT_BUTTON, self.OnPlayAudio)
        self.btn_play.Disable()
        
        self.btn_stop = wx.Button(self.panel, label=self._("stop_play"))
        self.btn_stop.Bind(wx.EVT_BUTTON, self.OnStopAudio)
        self.btn_stop.Disable()
        
        self.btn_save = wx.Button(self.panel, label=self._("save"))
        self.btn_save.Bind(wx.EVT_BUTTON, self.OnSaveAudio)
        self.btn_save.Disable()
        
        self.btn_delete = wx.Button(self.panel, label=self._("delete"))
        self.btn_delete.Bind(wx.EVT_BUTTON, self.OnDeleteAudio)
        self.btn_delete.Disable()
        
        hbox_audio.Add(self.btn_play, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_audio.Add(self.btn_stop, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_audio.Add(self.btn_save, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_audio.Add(self.btn_delete, 1, wx.EXPAND, 0)"""

code = code.replace(gen_audio_old, gen_audio_new)

# 2. Update clone reference audio buttons
ref_audio_old = """        self.btn_play_ref = wx.Button(tab, label=self._("play_ref"))
        self.btn_play_ref.Bind(wx.EVT_BUTTON, lambda e: self.TogglePlayFile(self.btn_play_ref, self.clone_ref_audio))
        
        self.btn_rec_ref = wx.Button(tab, label=self._("rec_ref"))
        self.btn_rec_ref.Bind(wx.EVT_BUTTON, lambda e: self.ToggleRecord(self.btn_rec_ref, self.clone_ref_audio))
        
        hbox_ref.Add(self.clone_ref_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(btn_browse, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_play_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_rec_ref, 0, wx.EXPAND, 0)"""

ref_audio_new = """        self.btn_play_ref = wx.Button(tab, label=self._("play_ref"))
        self.btn_stop_ref = wx.Button(tab, label=self._("stop_play"))
        self.btn_stop_ref.Disable()
        self.btn_play_ref.Bind(wx.EVT_BUTTON, lambda e: self.TogglePlayFile(self.btn_play_ref, self.btn_stop_ref, self.clone_ref_audio))
        self.btn_stop_ref.Bind(wx.EVT_BUTTON, lambda e: self.StopPlayFile(self.btn_play_ref, self.btn_stop_ref))
        
        self.btn_rec_ref = wx.Button(tab, label=self._("rec_ref"))
        self.btn_rec_ref.Bind(wx.EVT_BUTTON, lambda e: self.ToggleRecord(self.btn_rec_ref, self.clone_ref_audio))
        
        hbox_ref.Add(self.clone_ref_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(btn_browse, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_play_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_stop_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_rec_ref, 0, wx.EXPAND, 0)"""
        
code = code.replace(ref_audio_old, ref_audio_new)

# 3. Update preset audio buttons
preset_audio_old = """        self.btn_play_preset = wx.Button(tab, label=self._("play_ref"))
        self.btn_play_preset.Bind(wx.EVT_BUTTON, lambda e: self.TogglePlayFile(self.btn_play_preset, self.preset_audio))
        
        self.btn_rec_preset = wx.Button(tab, label=self._("rec_ref"))
        self.btn_rec_preset.Bind(wx.EVT_BUTTON, lambda e: self.ToggleRecord(self.btn_rec_preset, self.preset_audio))
        
        hbox1.Add(self.preset_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(btn_br, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_play_preset, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_rec_preset, 0, wx.EXPAND, 0)"""

preset_audio_new = """        self.btn_play_preset = wx.Button(tab, label=self._("play_ref"))
        self.btn_stop_preset = wx.Button(tab, label=self._("stop_play"))
        self.btn_stop_preset.Disable()
        self.btn_play_preset.Bind(wx.EVT_BUTTON, lambda e: self.TogglePlayFile(self.btn_play_preset, self.btn_stop_preset, self.preset_audio))
        self.btn_stop_preset.Bind(wx.EVT_BUTTON, lambda e: self.StopPlayFile(self.btn_play_preset, self.btn_stop_preset))
        
        self.btn_rec_preset = wx.Button(tab, label=self._("rec_ref"))
        self.btn_rec_preset.Bind(wx.EVT_BUTTON, lambda e: self.ToggleRecord(self.btn_rec_preset, self.preset_audio))
        
        hbox1.Add(self.preset_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(btn_br, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_play_preset, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_stop_preset, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox1.Add(self.btn_rec_preset, 0, wx.EXPAND, 0)"""

code = code.replace(preset_audio_old, preset_audio_new)

# Enable buttons on success
code = code.replace("self.btn_play.Enable()\n                self.btn_save.Enable()", "self.btn_play.Enable()\n                self.btn_save.Enable()\n                self.btn_delete.Enable()")

# 4. Update TogglePlayFile and add StopPlayFile
toggle_old = """    def TogglePlayFile(self, btn, path_ctrl):
        if btn.GetLabel() == self._("play_ref"):
            path = path_ctrl.GetValue().strip()
            if not os.path.exists(path):
                wx.MessageBox("Plik audio nie istnieje!", "Błąd", wx.OK | wx.ICON_ERROR)
                return
            try:
                data, fs = sf.read(path)
                sd.play(data, samplerate=fs)
                btn.SetLabel(self._("stop_play"))
                duration_ms = int((len(data) / fs) * 1000)
                timer = wx.CallLater(duration_ms + 100, lambda: btn.SetLabel(self._("play_ref")))
                setattr(self, f"timer_{id(btn)}", timer)
            except Exception as e:
                wx.MessageBox(f"Błąd odtwarzania: {str(e)}", "Błąd", wx.OK | wx.ICON_ERROR)
        else:
            if sd: sd.stop()
            timer = getattr(self, f"timer_{id(btn)}", None)
            if timer: timer.Stop()
            btn.SetLabel(self._("play_ref"))"""

toggle_new = """    def TogglePlayFile(self, btn_play, btn_stop, path_ctrl):
        path = path_ctrl.GetValue().strip()
        import time
        if btn_play.GetLabel() == self._("play_ref"):
            if not os.path.exists(path):
                wx.MessageBox("Plik audio nie istnieje!", self._("error_title"), wx.OK | wx.ICON_ERROR)
                return
                
            state_key = id(btn_play)
            if not hasattr(self, 'file_audio_states'):
                self.file_audio_states = {}
                
            state = self.file_audio_states.get(state_key, {'path': '', 'offset': 0, 'data': None, 'fs': 0})
            
            if state['path'] != path or state['data'] is None:
                try:
                    data, fs = sf.read(path)
                    state['data'] = data
                    state['fs'] = fs
                    state['path'] = path
                    state['offset'] = 0
                except Exception as e:
                    wx.MessageBox(f"Błąd odtwarzania: {str(e)}", self._("error_title"), wx.OK | wx.ICON_ERROR)
                    return
                    
            if state['offset'] >= len(state['data']):
                state['offset'] = 0
                
            remaining = state['data'][state['offset']:]
            sd.play(remaining, samplerate=state['fs'])
            state['start_time'] = time.time()
            
            btn_play.SetLabel("Pauza" if self.cfg.get("language", "pl") == "pl" else "Pause")
            btn_stop.Enable()
            
            duration_ms = int((len(remaining) / state['fs']) * 1000)
            timer = getattr(self, f"timer_{state_key}", None)
            if timer: timer.Stop()
            
            def on_finish():
                state['offset'] = 0
                btn_play.SetLabel(self._("play_ref"))
                btn_stop.Disable()
                
            timer = wx.CallLater(duration_ms + 50, on_finish)
            setattr(self, f"timer_{state_key}", timer)
            self.file_audio_states[state_key] = state
        else:
            if sd: sd.stop()
            state_key = id(btn_play)
            timer = getattr(self, f"timer_{state_key}", None)
            if timer: timer.Stop()
            
            state = self.file_audio_states.get(state_key)
            if state:
                elapsed = time.time() - state['start_time']
                state['offset'] += int(elapsed * state['fs'])
                
            btn_play.SetLabel(self._("play_ref"))
            
    def StopPlayFile(self, btn_play, btn_stop):
        if sd: sd.stop()
        state_key = id(btn_play)
        timer = getattr(self, f"timer_{state_key}", None)
        if timer: timer.Stop()
        
        state = getattr(self, 'file_audio_states', {}).get(state_key)
        if state:
            state['offset'] = 0
            
        btn_play.SetLabel(self._("play_ref"))
        btn_stop.Disable()"""

code = code.replace(toggle_old, toggle_new)

# 5. Update OnPlayAudio for Generated Audio and add OnStopAudio, OnDeleteAudio
onplay_old = """    def OnPlayAudio(self, event):
        if self.btn_play.GetLabel() == self._("play"):
            if self.audio_data is not None and sd:
                sd.play(self.audio_data, samplerate=self.sample_rate)
                self.btn_play.SetLabel(self._("stop_play"))
                duration_ms = int((len(self.audio_data) / self.sample_rate) * 1000)
                if hasattr(self, 'play_timer'): self.play_timer.Stop()
                self.play_timer = wx.CallLater(duration_ms + 100, lambda: self.btn_play.SetLabel(self._("play")))
        else:
            if sd: sd.stop()
            if hasattr(self, 'play_timer'): self.play_timer.Stop()
            self.btn_play.SetLabel(self._("play"))"""

onplay_new = """    def OnPlayAudio(self, event):
        import time
        if self.btn_play.GetLabel() == self._("play"):
            if self.audio_data is not None and sd:
                if not hasattr(self, 'gen_play_offset'):
                    self.gen_play_offset = 0
                if self.gen_play_offset >= len(self.audio_data):
                    self.gen_play_offset = 0
                    
                remaining = self.audio_data[self.gen_play_offset:]
                sd.play(remaining, samplerate=self.sample_rate)
                self.gen_play_start = time.time()
                
                self.btn_play.SetLabel("Pauza" if self.cfg.get("language", "pl") == "pl" else "Pause")
                self.btn_stop.Enable()
                
                duration_ms = int((len(remaining) / self.sample_rate) * 1000)
                if hasattr(self, 'gen_play_timer'): self.gen_play_timer.Stop()
                
                def on_finish():
                    self.gen_play_offset = 0
                    self.btn_play.SetLabel(self._("play"))
                    self.btn_stop.Disable()
                    
                self.gen_play_timer = wx.CallLater(duration_ms + 50, on_finish)
        else:
            if sd: sd.stop()
            if hasattr(self, 'gen_play_timer'): self.gen_play_timer.Stop()
            elapsed = time.time() - self.gen_play_start
            self.gen_play_offset += int(elapsed * self.sample_rate)
            self.btn_play.SetLabel(self._("play"))
            
    def OnStopAudio(self, event=None):
        if sd: sd.stop()
        if hasattr(self, 'gen_play_timer'): self.gen_play_timer.Stop()
        self.gen_play_offset = 0
        self.btn_play.SetLabel(self._("play"))
        self.btn_stop.Disable()
        
    def OnDeleteAudio(self, event):
        msg = "Czy na pewno chcesz usunąć wygenerowany plik z pamięci?" if self.cfg.get("language", "pl") == "pl" else "Are you sure you want to delete the generated audio from memory?"
        dlg = wx.MessageDialog(self, msg, self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            self.OnStopAudio()
            self.audio_data = None
            self.btn_play.Disable()
            self.btn_stop.Disable()
            self.btn_save.Disable()
            self.btn_delete.Disable()
            self.Log("Usunięto / Deleted", success=True)"""

code = code.replace(onplay_old, onplay_new)

# 6. Save language setting correctly
save_clone_lang_old = """self.clone_lang.SetValue("Auto")"""
save_clone_lang_new = """def_clone_lang = self.cfg.get("clone_lang", "Auto") if self.cfg.get("remember_ai_settings", True) else "Auto"
        self.clone_lang.SetValue(def_clone_lang)"""
code = code.replace(save_clone_lang_old, save_clone_lang_new)

save_design_lang_old = """self.design_lang.SetValue("Auto")"""
save_design_lang_new = """def_design_lang = self.cfg.get("design_lang", "Auto") if self.cfg.get("remember_ai_settings", True) else "Auto"
        self.design_lang.SetValue(def_design_lang)"""
code = code.replace(save_design_lang_old, save_design_lang_new)

# Append to OnCloseWindow
onclose_old = """            if hasattr(self, 'spin_steps'):
                self.cfg["ai_steps"] = self.spin_steps.GetValue()
                self.cfg["ai_cfg"] = self.spin_cfg.GetValue()
                self.cfg["ai_speed"] = self.spin_speed.GetValue()
                self.cfg["ai_denoise"] = self.chk_denoise.GetValue()
            SaveBasicConfig(self.cfg)"""

onclose_new = """            if hasattr(self, 'spin_steps'):
                self.cfg["ai_steps"] = self.spin_steps.GetValue()
                self.cfg["ai_cfg"] = self.spin_cfg.GetValue()
                self.cfg["ai_speed"] = self.spin_speed.GetValue()
                self.cfg["ai_denoise"] = self.chk_denoise.GetValue()
            if hasattr(self, 'clone_lang'):
                self.cfg["clone_lang"] = self.clone_lang.GetValue()
            if hasattr(self, 'design_lang'):
                self.cfg["design_lang"] = self.design_lang.GetValue()
            SaveBasicConfig(self.cfg)"""

code = code.replace(onclose_old, onclose_new)

with codecs.open("wx_app.py", "w", encoding="utf-8") as f:
    f.write(code)
