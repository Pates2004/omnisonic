import io

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

old_ai_reset = """    def OnResetAI(self, event):
        if wx.MessageBox(self._("reset_ai_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_WARNING) == wx.YES:
            self.cfg["ai_steps"] = 32
            self.cfg["ai_cfg"] = 2.0
            self.cfg["ai_speed"] = 1.0
            self.cfg["ai_denoise"] = True
            parent = self.GetParent()
            if hasattr(parent, 'spin_steps'):
                parent.spin_steps.SetValue(32)
                parent.spin_cfg.SetValue(2.0)
                parent.spin_speed.SetValue(1.0)
                parent.chk_denoise.SetValue(True)
            wx.MessageBox(self._("reset_ok"), self._("info_title"), wx.OK | wx.ICON_INFORMATION)"""
            
new_ai_reset = """    def OnResetAI(self, event):
        if wx.MessageBox(self._("reset_ai_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_WARNING) == wx.YES:
            self.cfg["ai_steps"] = 32
            self.cfg["ai_cfg"] = 2.0
            self.cfg["ai_speed"] = 1.0
            self.cfg["ai_denoise"] = True
            self.cfg["use_duration"] = False
            self.cfg["duration_val"] = 5.0
            parent = self.GetParent()
            if hasattr(parent, 'spin_steps'):
                parent.spin_steps.SetValue(32)
                parent.spin_cfg.SetValue(2.0)
                parent.spin_speed.SetValue(1.0)
                parent.chk_denoise.SetValue(True)
                if hasattr(parent, 'chk_duration'):
                    parent.chk_duration.SetValue(False)
                    parent.spin_duration.SetValue(5.0)
            wx.MessageBox(self._("reset_ok"), self._("info_title"), wx.OK | wx.ICON_INFORMATION)"""
            
code = code.replace(old_ai_reset, new_ai_reset)

old_app_reset = """    def OnResetApp(self, event):
        if wx.MessageBox(self._("reset_app_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_WARNING) == wx.YES:
            self.cb_lang.SetSelection(self.avail_langs.index("pl") if "pl" in self.avail_langs else 0)
            self.cb_theme.SetSelection(0)
            self.spin_font.SetValue(10)
            self.chk_console.SetValue(False)
            self.chk_close_console.SetValue(True)
            self.chk_force_splash.SetValue(False)
            self.chk_show_progress.SetValue(True)
            self.chk_fake_progress.SetValue(False)
            self.chk_use_native.SetValue(False)
            self.chk_validate.SetValue(False)
            self.chk_warn_exit.SetValue(True)
            self.chk_confirm_success.SetValue(False)
            self.chk_remember_ai.SetValue(True)
            self.chk_clean_temp.SetValue(True)
            wx.MessageBox(self._("reset_ok"), self._("info_title"), wx.OK | wx.ICON_INFORMATION)"""

new_app_reset = """    def OnResetApp(self, event):
        if wx.MessageBox(self._("reset_app_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_WARNING) == wx.YES:
            self.cb_lang.SetSelection(self.avail_langs.index("pl") if "pl" in self.avail_langs else 0)
            self.cb_theme.SetSelection(0)
            self.spin_font.SetValue(10)
            self.chk_console.SetValue(False)
            self.chk_close_console.SetValue(True)
            self.chk_force_splash.SetValue(False)
            self.chk_show_progress.SetValue(True)
            self.chk_fake_progress.SetValue(False)
            self.chk_use_native.SetValue(False)
            self.chk_validate.SetValue(False)
            self.chk_warn_exit.SetValue(True)
            self.chk_confirm_success.SetValue(False)
            self.chk_remember_ai.SetValue(True)
            self.chk_clean_temp.SetValue(True)
            self.cfg["warn_delete_preset"] = True
            wx.MessageBox(self._("reset_ok"), self._("info_title"), wx.OK | wx.ICON_INFORMATION)"""

code = code.replace(old_app_reset, new_app_reset)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
