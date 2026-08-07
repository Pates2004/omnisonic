import io
import re

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Replace OnSavePreset and _SavePresetWorker
old_methods = """    def OnSavePreset(self, event):
        if not self.model:
            wx.MessageBox(self._("msg_load_first"), self._("error_title"))
            return
            
        ref_audio = self.preset_audio.GetValue().strip()
        ref_text = self.preset_ref_text.GetValue().strip() or None
        name = self.preset_name.GetValue().strip()
        
        if not os.path.exists(ref_audio) or not name:
            wx.MessageBox(self._("err_bad_preset_name"), self._("error_title"), wx.OK | wx.ICON_ERROR)
            return
            
        def on_success():
            self.Log(self._("ready"), success=True)
            self.RefreshPresets()
            self.preset_name.SetValue("")
            msg = self._("preset_created_msg").replace("{name}", name)
            wx.MessageBox(msg, self._("success_title"), wx.OK | wx.ICON_INFORMATION)
            
        self.RunOperation("op_preset_title", "op_preset_msg", self._SavePresetWorker, ref_audio, ref_text, name, success_callback=on_success)
        
    def _SavePresetWorker(self, op_dialog, ref_audio, ref_text, name):
        try:
            if op_dialog.cancel_flag: return
            prompt = self.model.create_voice_clone_prompt(ref_audio=ref_audio, ref_text=ref_text)
            if op_dialog.cancel_flag: return
            
            if not name.endswith(".pt"): name += ".pt"
            path = os.path.join(PRESETS_DIR, name)
            prompt.save(path)
            wx.CallAfter(self.Log, f"Preset zapisany: {path}")
        except Exception as e:
            if not op_dialog.cancel_flag:
                wx.CallAfter(self.Log, self._("msg_error") + str(e))"""

new_methods = """    def OnSavePresetPrompt(self, event):
        if not self.model:
            wx.MessageBox(self._("msg_load_first"), self._("error_title"))
            return
            
        ref_audio = self.clone_ref_audio.GetValue().strip()
        ref_text = self.clone_ref_text.GetValue().strip() or None
        
        if not os.path.exists(ref_audio):
            wx.MessageBox(self._("err_file_not_found"), self._("error_title"), wx.OK | wx.ICON_ERROR)
            return
            
        dlg = wx.TextEntryDialog(self, self._("prompt_preset_name"), self._("preset_name_title"))
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if not name:
                wx.MessageBox(self._("err_bad_preset_name"), self._("error_title"), wx.OK | wx.ICON_ERROR)
                dlg.Destroy()
                return
            
            def on_success():
                self.Log(self._("ready"), success=True)
                self.RefreshPresets()
                msg = self._("preset_created_msg").replace("{name}", name)
                if self.cfg.get("confirm_success", False):
                    wx.MessageBox(msg, self._("success_title"), wx.OK | wx.ICON_INFORMATION)
                
            self.RunOperation("op_preset_title", "op_preset_msg", self._SavePresetWorker, ref_audio, ref_text, name, success_callback=on_success)
        dlg.Destroy()
        
    def _SavePresetWorker(self, op_dialog, ref_audio, ref_text, name):
        try:
            if op_dialog.cancel_flag: return
            prompt = self.model.create_voice_clone_prompt(ref_audio=ref_audio, ref_text=ref_text)
            if op_dialog.cancel_flag: return
            
            if not name.endswith(".pt"): name += ".pt"
            if not os.path.exists(PRESETS_DIR):
                os.makedirs(PRESETS_DIR)
            path = os.path.join(PRESETS_DIR, name)
            prompt.save(path)
            wx.CallAfter(self.Log, f"Preset zapisany: {path}")
        except Exception as e:
            if not op_dialog.cancel_flag:
                wx.CallAfter(self.Log, self._("msg_error") + str(e))
                
    def _CheckDeleteWarning(self, msg):
        if not self.cfg.get("warn_delete_preset", True):
            return True
        dlg = wx.RichMessageDialog(self, msg, self._("warning_title"), wx.YES_NO | wx.ICON_WARNING)
        dlg.ShowCheckBox(self._("warn_no_show"))
        res = dlg.ShowModal()
        if dlg.IsCheckBoxChecked():
            self.cfg["warn_delete_preset"] = False
            self.SaveConfig()
        return res == wx.ID_YES
                
    def OnDelPreset(self, event):
        idx = self.combo_presets.GetSelection()
        pt = self.combo_presets.GetClientData(idx)
        if not pt:
            wx.MessageBox(self._("msg_no_preset_sel"), self._("error_title"), wx.OK | wx.ICON_ERROR)
            return
            
        name = pt.replace(".pt", "")
        if not self._CheckDeleteWarning(self._("warn_del_preset").replace("{name}", name)):
            return
            
        path = os.path.join(PRESETS_DIR, pt)
        if os.path.exists(path):
            os.remove(path)
        self.RefreshPresets()
        
    def OnDelAllPresets(self, event):
        if not self._CheckDeleteWarning(self._("warn_del_all")):
            return
            
        if os.path.exists(PRESETS_DIR):
            for f in os.listdir(PRESETS_DIR):
                if f.endswith(".pt"):
                    os.remove(os.path.join(PRESETS_DIR, f))
        self.RefreshPresets()
        wx.MessageBox(self._("msg_presets_deleted"), self._("success_title"), wx.OK | wx.ICON_INFORMATION)
        
    def OnPresetKeyDown(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_DELETE:
            idx = self.combo_presets.GetSelection()
            pt = self.combo_presets.GetClientData(idx)
            if not pt:
                event.Skip()
                return
                
            path = os.path.join(PRESETS_DIR, pt)
            if event.ShiftDown():
                # Force delete
                if os.path.exists(path):
                    os.remove(path)
                self.RefreshPresets()
            else:
                name = pt.replace(".pt", "")
                if self._CheckDeleteWarning(self._("warn_del_preset").replace("{name}", name)):
                    if os.path.exists(path):
                        os.remove(path)
                    self.RefreshPresets()
        else:
            event.Skip()"""

code = code.replace(old_methods, new_methods)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
