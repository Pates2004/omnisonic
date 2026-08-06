import codecs

with codecs.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

settings_old = """    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        if self.is_first_run:
            lbl = wx.StaticText(panel, label=self._("first_run_msg"))
            vbox.Add(lbl, 0, wx.ALL | wx.EXPAND, 10)
            
        wx.StaticText(panel, label=self._("lang_lbl"))
        self.avail_langs = list(LOCALE.keys())
        choices = [LOCALE[l].get("lang_name", l) for l in self.avail_langs]
        self.cb_lang = wx.ComboBox(panel, choices=choices, style=wx.CB_READONLY)
        self.cb_lang.SetName(self._("lang_lbl"))
        self.cb_lang.SetSelection(self.avail_langs.index(self.lang) if self.lang in self.avail_langs else 0)
        vbox.Add(self.cb_lang, 0, wx.ALL | wx.EXPAND, 5)
        
        wx.StaticText(panel, label=self._("theme_lbl"))
        self.cb_theme = wx.ComboBox(panel, choices=[self._("theme_light"), self._("theme_dark")], style=wx.CB_READONLY)
        self.cb_theme.SetName(self._("theme_lbl"))
        self.cb_theme.SetSelection(0 if self.cfg.get("theme", "light") == "light" else 1)
        vbox.Add(self.cb_theme, 0, wx.ALL | wx.EXPAND, 5)
        
        wx.StaticText(panel, label=self._("font_size_lbl"))
        self.spin_font = wx.SpinCtrl(panel, value=str(self.cfg.get("font_size", 10)), min=8, max=24)
        self.spin_font.SetName(self._("font_size_lbl"))
        vbox.Add(self.spin_font, 0, wx.ALL | wx.EXPAND, 5)
        
        if not self.is_first_run:
            self.chk_console = wx.CheckBox(panel, label=self._("console_lbl"))
            self.chk_console.SetValue(self.cfg.get("show_console", False))
            vbox.Add(self.chk_console, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_close_console = wx.CheckBox(panel, label=self._("close_console_lbl"))
            self.chk_close_console.SetValue(self.cfg.get("close_console_on_exit", True))
            vbox.Add(self.chk_close_console, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_force_splash = wx.CheckBox(panel, label=self._("force_splash_lbl"))
            self.chk_force_splash.SetValue(self.cfg.get("force_splash", False))
            vbox.Add(self.chk_force_splash, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_show_progress = wx.CheckBox(panel, label=self._("show_progress_lbl"))
            self.chk_show_progress.SetValue(self.cfg.get("show_progress", True))
            vbox.Add(self.chk_show_progress, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_use_native = wx.CheckBox(panel, label=self._("use_native_dialogs_lbl"))
            self.chk_use_native.SetValue(self.cfg.get("use_native_dialogs", False))
            vbox.Add(self.chk_use_native, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_validate = wx.CheckBox(panel, label=self._("validate_lbl"))
            self.chk_validate.SetValue(self.cfg.get("validate_components", False))
            vbox.Add(self.chk_validate, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_warn_exit = wx.CheckBox(panel, label=self._("warn_exit_lbl"))
            self.chk_warn_exit.SetValue(self.cfg.get("warn_exit", True))
            vbox.Add(self.chk_warn_exit, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_confirm_success = wx.CheckBox(panel, label=self._("confirm_success_lbl"))
            self.chk_confirm_success.SetValue(self.cfg.get("confirm_success", False))
            vbox.Add(self.chk_confirm_success, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_remember_ai = wx.CheckBox(panel, label=self._("remember_ai_lbl"))
            self.chk_remember_ai.SetValue(self.cfg.get("remember_ai_settings", True))
            vbox.Add(self.chk_remember_ai, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_clean_temp = wx.CheckBox(panel, label=self._("clean_temp_lbl"))
            self.chk_clean_temp.SetValue(self.cfg.get("clean_temp", True))
            vbox.Add(self.chk_clean_temp, 0, wx.ALL | wx.EXPAND, 5)
            
            self.btn_clean_temp = wx.Button(panel, label=self._("clean_temp_btn"))
            self.btn_clean_temp.Bind(wx.EVT_BUTTON, self.OnCleanTemp)
            vbox.Add(self.btn_clean_temp, 0, wx.ALL | wx.EXPAND, 5)
            
            hbox_reset = wx.BoxSizer(wx.HORIZONTAL)
            self.btn_reset_ai = wx.Button(panel, label=self._("reset_ai_btn"))
            self.btn_reset_app = wx.Button(panel, label=self._("reset_app_btn"))
            
            self.btn_reset_ai.Bind(wx.EVT_BUTTON, self.OnResetAI)
            self.btn_reset_app.Bind(wx.EVT_BUTTON, self.OnResetApp)
            
            hbox_reset.Add(self.btn_reset_ai, 1, wx.EXPAND | wx.RIGHT, 5)
            hbox_reset.Add(self.btn_reset_app, 1, wx.EXPAND, 0)
            vbox.Add(hbox_reset, 0, wx.ALL | wx.EXPAND, 5)
            
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(panel, label="OK")
        btn_cancel = wx.Button(panel, label=self._("cancel"))
        
        btn_ok.Bind(wx.EVT_BUTTON, self.OnSave)
        btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        
        hbox.Add(btn_ok, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox.Add(btn_cancel, 1, wx.EXPAND, 0)
        
        vbox.Add(hbox, 0, wx.ALL | wx.EXPAND, 5)
        
        panel.SetSizer(vbox)"""

settings_new = """    def InitUI(self):
        panel = wx.Panel(self)
        vbox_main = wx.BoxSizer(wx.VERTICAL)
        
        if self.is_first_run:
            lbl = wx.StaticText(panel, label=self._("first_run_msg"))
            vbox_main.Add(lbl, 0, wx.ALL | wx.EXPAND, 10)
            
        notebook = wx.Notebook(panel)
        tab_app = wx.Panel(notebook)
        tab_sys = wx.Panel(notebook)
        tab_opts = wx.Panel(notebook)
        
        notebook.AddPage(tab_app, "Wygląd i Język" if self.lang == "pl" else "Appearance & Language")
        if not self.is_first_run:
            notebook.AddPage(tab_sys, "System i Presety" if self.lang == "pl" else "System & Presets")
            notebook.AddPage(tab_opts, "Opcje AI" if self.lang == "pl" else "AI Options")
            
        vbox_app = wx.BoxSizer(wx.VERTICAL)
        wx.StaticText(tab_app, label=self._("lang_lbl"))
        self.avail_langs = list(LOCALE.keys())
        choices = [LOCALE[l].get("lang_name", l) for l in self.avail_langs]
        self.cb_lang = wx.ComboBox(tab_app, choices=choices, style=wx.CB_READONLY)
        self.cb_lang.SetName(self._("lang_lbl"))
        self.cb_lang.SetSelection(self.avail_langs.index(self.lang) if self.lang in self.avail_langs else 0)
        vbox_app.Add(self.cb_lang, 0, wx.ALL | wx.EXPAND, 5)
        
        wx.StaticText(tab_app, label=self._("theme_lbl"))
        self.cb_theme = wx.ComboBox(tab_app, choices=[self._("theme_light"), self._("theme_dark")], style=wx.CB_READONLY)
        self.cb_theme.SetName(self._("theme_lbl"))
        self.cb_theme.SetSelection(0 if self.cfg.get("theme", "light") == "light" else 1)
        vbox_app.Add(self.cb_theme, 0, wx.ALL | wx.EXPAND, 5)
        
        wx.StaticText(tab_app, label=self._("font_size_lbl"))
        self.spin_font = wx.SpinCtrl(tab_app, value=str(self.cfg.get("font_size", 10)), min=8, max=24)
        self.spin_font.SetName(self._("font_size_lbl"))
        vbox_app.Add(self.spin_font, 0, wx.ALL | wx.EXPAND, 5)
        tab_app.SetSizer(vbox_app)
        
        if not self.is_first_run:
            vbox_sys = wx.BoxSizer(wx.VERTICAL)
            
            self.chk_console = wx.CheckBox(tab_sys, label=self._("console_lbl"))
            self.chk_console.SetValue(self.cfg.get("show_console", False))
            vbox_sys.Add(self.chk_console, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_close_console = wx.CheckBox(tab_sys, label=self._("close_console_lbl"))
            self.chk_close_console.SetValue(self.cfg.get("close_console_on_exit", True))
            vbox_sys.Add(self.chk_close_console, 0, wx.ALL | wx.EXPAND, 5)
            
            wx.StaticText(tab_sys, label="Styl wyświetlania presetów:" if self.lang == "pl" else "Preset display style:")
            self.cb_preset_disp = wx.ComboBox(tab_sys, choices=["Tylko nazwa / Name only", "Pełna ścieżka / Full path", "Nazwa i ścieżka / Name and path"], style=wx.CB_READONLY)
            cur_disp = self.cfg.get("preset_display_mode", "name")
            if cur_disp == "name": self.cb_preset_disp.SetSelection(0)
            elif cur_disp == "path": self.cb_preset_disp.SetSelection(1)
            else: self.cb_preset_disp.SetSelection(2)
            vbox_sys.Add(self.cb_preset_disp, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_clean_temp = wx.CheckBox(tab_sys, label=self._("clean_temp_lbl"))
            self.chk_clean_temp.SetValue(self.cfg.get("clean_temp", True))
            vbox_sys.Add(self.chk_clean_temp, 0, wx.ALL | wx.EXPAND, 5)
            
            self.btn_clean_temp = wx.Button(tab_sys, label=self._("clean_temp_btn"))
            self.btn_clean_temp.Bind(wx.EVT_BUTTON, self.OnCleanTemp)
            vbox_sys.Add(self.btn_clean_temp, 0, wx.ALL | wx.EXPAND, 5)
            tab_sys.SetSizer(vbox_sys)
            
            vbox_opts = wx.BoxSizer(wx.VERTICAL)
            
            self.chk_force_splash = wx.CheckBox(tab_opts, label=self._("force_splash_lbl"))
            self.chk_force_splash.SetValue(self.cfg.get("force_splash", False))
            vbox_opts.Add(self.chk_force_splash, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_show_progress = wx.CheckBox(tab_opts, label=self._("show_progress_lbl"))
            self.chk_show_progress.SetValue(self.cfg.get("show_progress", True))
            vbox_opts.Add(self.chk_show_progress, 0, wx.ALL | wx.EXPAND, 5)
            
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
            vbox_opts.Add(self.chk_remember_ai, 0, wx.ALL | wx.EXPAND, 5)
            
            hbox_reset = wx.BoxSizer(wx.HORIZONTAL)
            self.btn_reset_ai = wx.Button(tab_opts, label=self._("reset_ai_btn"))
            self.btn_reset_app = wx.Button(tab_opts, label=self._("reset_app_btn"))
            
            self.btn_reset_ai.Bind(wx.EVT_BUTTON, self.OnResetAI)
            self.btn_reset_app.Bind(wx.EVT_BUTTON, self.OnResetApp)
            
            hbox_reset.Add(self.btn_reset_ai, 1, wx.EXPAND | wx.RIGHT, 5)
            hbox_reset.Add(self.btn_reset_app, 1, wx.EXPAND, 0)
            vbox_opts.Add(hbox_reset, 0, wx.ALL | wx.EXPAND, 5)
            tab_opts.SetSizer(vbox_opts)
            
        vbox_main.Add(notebook, 1, wx.EXPAND | wx.ALL, 5)
            
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(panel, label="OK")
        btn_cancel = wx.Button(panel, label=self._("cancel"))
        
        btn_ok.Bind(wx.EVT_BUTTON, self.OnSave)
        btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        
        hbox.Add(btn_ok, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox.Add(btn_cancel, 1, wx.EXPAND, 0)
        
        vbox_main.Add(hbox, 0, wx.ALL | wx.EXPAND, 5)
        
        panel.SetSizer(vbox_main)"""
        
code = code.replace(settings_old, settings_new)

save_old = """    def OnSave(self, event):
        self.cfg["language"] = self.avail_langs[self.cb_lang.GetSelection()]
        self.cfg["theme"] = "light" if self.cb_theme.GetSelection() == 0 else "dark"
        self.cfg["font_size"] = self.spin_font.GetValue()
        
        if not self.is_first_run:
            self.cfg["show_console"] = self.chk_console.GetValue()
            self.cfg["close_console_on_exit"] = self.chk_close_console.GetValue()
            self.cfg["force_splash"] = self.chk_force_splash.GetValue()
            self.cfg["show_progress"] = self.chk_show_progress.GetValue()
            self.cfg["use_native_dialogs"] = self.chk_use_native.GetValue()
            self.cfg["validate_components"] = self.chk_validate.GetValue()
            self.cfg["warn_exit"] = self.chk_warn_exit.GetValue()
            self.cfg["confirm_success"] = self.chk_confirm_success.GetValue()
            self.cfg["remember_ai_settings"] = self.chk_remember_ai.GetValue()
            self.cfg["clean_temp"] = self.chk_clean_temp.GetValue()"""
            
save_new = """    def OnSave(self, event):
        self.cfg["language"] = self.avail_langs[self.cb_lang.GetSelection()]
        self.cfg["theme"] = "light" if self.cb_theme.GetSelection() == 0 else "dark"
        self.cfg["font_size"] = self.spin_font.GetValue()
        
        if not self.is_first_run:
            self.cfg["show_console"] = self.chk_console.GetValue()
            self.cfg["close_console_on_exit"] = self.chk_close_console.GetValue()
            idx = self.cb_preset_disp.GetSelection()
            self.cfg["preset_display_mode"] = "name" if idx == 0 else ("path" if idx == 1 else "name_path")
            self.cfg["force_splash"] = self.chk_force_splash.GetValue()
            self.cfg["show_progress"] = self.chk_show_progress.GetValue()
            self.cfg["use_native_dialogs"] = self.chk_use_native.GetValue()
            self.cfg["validate_components"] = self.chk_validate.GetValue()
            self.cfg["warn_exit"] = self.chk_warn_exit.GetValue()
            self.cfg["confirm_success"] = self.chk_confirm_success.GetValue()
            self.cfg["remember_ai_settings"] = self.chk_remember_ai.GetValue()
            self.cfg["clean_temp"] = self.chk_clean_temp.GetValue()"""

code = code.replace(save_old, save_new)

with codecs.open("wx_app.py", "w", encoding="utf-8") as f:
    f.write(code)
