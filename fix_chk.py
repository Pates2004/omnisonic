import io

with io.open("langs/pl.lng", "r", encoding="utf-8") as f:
    pl = f.read()
    
pl = pl.replace('"tab_ai_opts": "Opcje AI",', '"tab_ai_opts": "Opcje Aplikacji",')
    
with io.open("langs/pl.lng", "w", encoding="utf-8", newline="") as f:
    f.write(pl)

with io.open("langs/en.lng", "r", encoding="utf-8") as f:
    en = f.read()

en = en.replace('"tab_ai_opts": "AI Options",', '"tab_ai_opts": "App Options",')
    
with io.open("langs/en.lng", "w", encoding="utf-8", newline="") as f:
    f.write(en)
    
with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()
    
# Add SetName to checkboxes in SettingsDialog

old_chk = """            self.chk_force_splash = wx.CheckBox(tab_opts, label=self._("force_splash_lbl"))
            self.chk_force_splash.SetValue(self.cfg.get("force_splash", False))
            vbox_opts.Add(self.chk_force_splash, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_show_progress = wx.CheckBox(tab_opts, label=self._("show_progress_lbl"))
            self.chk_show_progress.SetValue(self.cfg.get("show_progress", True))
            vbox_opts.Add(self.chk_show_progress, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_fake_progress = wx.CheckBox(tab_opts, label=self._("fake_progress_lbl"))
            self.chk_fake_progress.SetValue(self.cfg.get("fake_progress_numbers", False))
            vbox_opts.Add(self.chk_fake_progress, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_use_native = wx.CheckBox(tab_opts, label=self._("use_native_dialogs_lbl"))
            self.chk_use_native.SetValue(self.cfg.get("use_native_dialogs", False))
            vbox_opts.Add(self.chk_use_native, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_validate = wx.CheckBox(tab_opts, label=self._("validate_lbl"))
            self.chk_validate.SetValue(self.cfg.get("validate_components", False))
            vbox_opts.Add(self.chk_validate, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_warn_exit = wx.CheckBox(tab_opts, label=self._("warn_exit_lbl"))
            self.chk_warn_exit.SetValue(self.cfg.get("warn_exit", True))
            vbox_opts.Add(self.chk_warn_exit, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_confirm_success = wx.CheckBox(tab_opts, label=self._("confirm_success_lbl"))
            self.chk_confirm_success.SetValue(self.cfg.get("confirm_success", False))
            vbox_opts.Add(self.chk_confirm_success, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_remember_ai = wx.CheckBox(tab_opts, label=self._("remember_ai_lbl"))
            self.chk_remember_ai.SetValue(self.cfg.get("remember_ai_settings", True))
            vbox_opts.Add(self.chk_remember_ai, 0, wx.ALL | wx.EXPAND, 5)"""
            
new_chk = """            self.chk_force_splash = wx.CheckBox(tab_opts, label=self._("force_splash_lbl"))
            self.chk_force_splash.SetName(self._("force_splash_lbl"))
            self.chk_force_splash.SetValue(self.cfg.get("force_splash", False))
            vbox_opts.Add(self.chk_force_splash, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_show_progress = wx.CheckBox(tab_opts, label=self._("show_progress_lbl"))
            self.chk_show_progress.SetName(self._("show_progress_lbl"))
            self.chk_show_progress.SetValue(self.cfg.get("show_progress", True))
            vbox_opts.Add(self.chk_show_progress, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_fake_progress = wx.CheckBox(tab_opts, label=self._("fake_progress_lbl"))
            self.chk_fake_progress.SetName(self._("fake_progress_lbl"))
            self.chk_fake_progress.SetValue(self.cfg.get("fake_progress_numbers", False))
            vbox_opts.Add(self.chk_fake_progress, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_use_native = wx.CheckBox(tab_opts, label=self._("use_native_dialogs_lbl"))
            self.chk_use_native.SetName(self._("use_native_dialogs_lbl"))
            self.chk_use_native.SetValue(self.cfg.get("use_native_dialogs", False))
            vbox_opts.Add(self.chk_use_native, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_validate = wx.CheckBox(tab_opts, label=self._("validate_lbl"))
            self.chk_validate.SetName(self._("validate_lbl"))
            self.chk_validate.SetValue(self.cfg.get("validate_components", False))
            vbox_opts.Add(self.chk_validate, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_warn_exit = wx.CheckBox(tab_opts, label=self._("warn_exit_lbl"))
            self.chk_warn_exit.SetName(self._("warn_exit_lbl"))
            self.chk_warn_exit.SetValue(self.cfg.get("warn_exit", True))
            vbox_opts.Add(self.chk_warn_exit, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_confirm_success = wx.CheckBox(tab_opts, label=self._("confirm_success_lbl"))
            self.chk_confirm_success.SetName(self._("confirm_success_lbl"))
            self.chk_confirm_success.SetValue(self.cfg.get("confirm_success", False))
            vbox_opts.Add(self.chk_confirm_success, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_remember_ai = wx.CheckBox(tab_opts, label=self._("remember_ai_lbl"))
            self.chk_remember_ai.SetName(self._("remember_ai_lbl"))
            self.chk_remember_ai.SetValue(self.cfg.get("remember_ai_settings", True))
            vbox_opts.Add(self.chk_remember_ai, 0, wx.ALL | wx.EXPAND, 5)"""

code = code.replace(old_chk, new_chk)

# Fix system tab
old_sys = """            self.chk_console = wx.CheckBox(tab_sys, label=self._("console_lbl"))
            self.chk_console.SetValue(self.cfg.get("show_console", False))
            vbox_sys.Add(self.chk_console, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_close_console = wx.CheckBox(tab_sys, label=self._("close_console_lbl"))
            self.chk_close_console.SetValue(self.cfg.get("close_console_on_exit", True))
            vbox_sys.Add(self.chk_close_console, 0, wx.ALL | wx.EXPAND, 5)
            
            wx.StaticText(tab_sys, label=self._("preset_disp_lbl"))
            self.cb_preset_disp = wx.ComboBox(tab_sys, choices=[self._("disp_name"), self._("disp_path"), self._("disp_both")], style=wx.CB_READONLY)
            cur_disp = self.cfg.get("preset_display_mode", "name")
            if cur_disp == "name": self.cb_preset_disp.SetSelection(0)
            elif cur_disp == "path": self.cb_preset_disp.SetSelection(1)
            else: self.cb_preset_disp.SetSelection(2)
            vbox_sys.Add(self.cb_preset_disp, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_clean_temp = wx.CheckBox(tab_sys, label=self._("clean_temp_lbl"))
            self.chk_clean_temp.SetValue(self.cfg.get("clean_temp", True))
            vbox_sys.Add(self.chk_clean_temp, 0, wx.ALL | wx.EXPAND, 5)"""

new_sys = """            self.chk_console = wx.CheckBox(tab_sys, label=self._("console_lbl"))
            self.chk_console.SetName(self._("console_lbl"))
            self.chk_console.SetValue(self.cfg.get("show_console", False))
            vbox_sys.Add(self.chk_console, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_close_console = wx.CheckBox(tab_sys, label=self._("close_console_lbl"))
            self.chk_close_console.SetName(self._("close_console_lbl"))
            self.chk_close_console.SetValue(self.cfg.get("close_console_on_exit", True))
            vbox_sys.Add(self.chk_close_console, 0, wx.ALL | wx.EXPAND, 5)
            
            wx.StaticText(tab_sys, label=self._("preset_disp_lbl"))
            self.cb_preset_disp = wx.ComboBox(tab_sys, choices=[self._("disp_name"), self._("disp_path"), self._("disp_both")], style=wx.CB_READONLY)
            self.cb_preset_disp.SetName(self._("preset_disp_lbl"))
            cur_disp = self.cfg.get("preset_display_mode", "name")
            if cur_disp == "name": self.cb_preset_disp.SetSelection(0)
            elif cur_disp == "path": self.cb_preset_disp.SetSelection(1)
            else: self.cb_preset_disp.SetSelection(2)
            vbox_sys.Add(self.cb_preset_disp, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_clean_temp = wx.CheckBox(tab_sys, label=self._("clean_temp_lbl"))
            self.chk_clean_temp.SetName(self._("clean_temp_lbl"))
            self.chk_clean_temp.SetValue(self.cfg.get("clean_temp", True))
            vbox_sys.Add(self.chk_clean_temp, 0, wx.ALL | wx.EXPAND, 5)"""

code = code.replace(old_sys, new_sys)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
