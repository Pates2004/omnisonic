import codecs
import re

with codecs.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update SettingsDialog to add 'normalize_text', 'asr_model_name'
settings_old = """            self.chk_notify_pop = wx.CheckBox(tab_opts, label=self._("notify_pop_lbl"))
            self.chk_notify_pop.SetValue(self.cfg.get("notify_popup", False))
            vbox_opts.Add(self.chk_notify_pop, 0, wx.ALL | wx.EXPAND, 5)"""
            
settings_new = """            self.chk_notify_pop = wx.CheckBox(tab_opts, label=self._("notify_pop_lbl"))
            self.chk_notify_pop.SetValue(self.cfg.get("notify_popup", False))
            vbox_opts.Add(self.chk_notify_pop, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_norm_text = wx.CheckBox(tab_opts, label=self._("norm_text_lbl") if hasattr(self, '_') and self._("norm_text_lbl") != "norm_text_lbl" else "Normalizuj tekst (zamienia 123 na słowa)")
            self.chk_norm_text.SetValue(self.cfg.get("normalize_text", False))
            vbox_opts.Add(self.chk_norm_text, 0, wx.ALL | wx.EXPAND, 5)
            
            wx.StaticText(tab_opts, label="Model Whisper (zostaw puste dla domyślnego openai/whisper-large-v3-turbo):")
            self.tc_asr_model = wx.TextCtrl(tab_opts, value=self.cfg.get("asr_model_name", ""))
            vbox_opts.Add(self.tc_asr_model, 0, wx.ALL | wx.EXPAND, 5)"""
code = code.replace(settings_old, settings_new)

save_cfg_old = """            self.cfg["notify_popup"] = self.chk_notify_pop.GetValue()"""
save_cfg_new = """            self.cfg["notify_popup"] = self.chk_notify_pop.GetValue()
            self.cfg["normalize_text"] = self.chk_norm_text.GetValue()
            self.cfg["asr_model_name"] = self.tc_asr_model.GetValue().strip()"""
code = code.replace(save_cfg_old, save_cfg_new)

# 2. Update OmniVoiceFrame to include Auto Voice Tab
init_notebook_old = """        self.notebook.AddPage(self.tab_clone, self._("clone_voice"))
        self.notebook.AddPage(self.tab_design, self._("design_voice"))
        self.notebook.AddPage(self.tab_preset, self._("presets"))"""
        
init_notebook_new = """        self.tab_auto = wx.Panel(self.notebook)
        self.SetupAutoTab(self.tab_auto)
        
        self.notebook.AddPage(self.tab_clone, self._("clone_voice"))
        self.notebook.AddPage(self.tab_design, self._("design_voice"))
        self.notebook.AddPage(self.tab_auto, self._("auto_voice") if hasattr(self, '_') and self._("auto_voice") != "auto_voice" else "Auto Voice")
        self.notebook.AddPage(self.tab_preset, self._("presets"))"""
code = code.replace(init_notebook_old, init_notebook_new)

# Add SetupAutoTab
setupauto = """
    def SetupAutoTab(self, tab):
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        wx.StaticText(tab, label="Tekst:")
        self.auto_text = wx.TextCtrl(tab, style=wx.TE_MULTILINE)
        vbox.Add(self.auto_text, 1, wx.EXPAND | wx.ALL, 5)
        
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        wx.StaticText(tab, label="Język / Language:")
        self.auto_lang = wx.ComboBox(tab, choices=_ALL_LANGUAGES, style=wx.CB_READONLY)
        self.auto_lang.SetSelection(0)
        hbox.Add(self.auto_lang, 0, wx.RIGHT, 10)
        
        self.btn_gen_auto = wx.Button(tab, label="Generuj (Losowy głos)")
        self.btn_gen_auto.Bind(wx.EVT_BUTTON, self.OnGenAuto)
        hbox.Add(self.btn_gen_auto, 0, wx.ALL, 0)
        
        vbox.Add(hbox, 0, wx.EXPAND | wx.ALL, 5)
        tab.SetSizer(vbox)

    def OnGenAuto(self, event):
        if not self.model:
            wx.MessageBox(self._("msg_load_first"), self._("error_title"))
            return
        text = self.auto_text.GetValue().strip()
        lang = self.auto_lang.GetValue()
        if lang == "Auto": lang = None
        speed = self.spin_speed.GetValue()
        duration = self.spin_duration.GetValue() if self.chk_duration.GetValue() else None
        norm_txt = self.cfg.get("normalize_text", False)
        if not text: return
            
        def on_success():
            if self.audio_data is not None:
                self.Log(self._("ready"), success=True)
                self.btn_play.Enable()
                self.btn_save.Enable()
                self.btn_play.SetFocus()
                wx.Bell()
                
        self.RunOperation("Generowanie", "Trwa generowanie losowego głosu...", self._GenAutoWorker, text, lang, speed, duration, norm_txt, success_callback=on_success)

    def _GenAutoWorker(self, op_dialog, text, lang, speed, duration, norm_txt):
        try:
            gen_config = self.GetGenConfig()
            if op_dialog.cancel_flag: return
            kwargs = {"text": text, "generation_config": gen_config, "normalize_text": norm_txt}
            if lang: kwargs["language"] = lang
            if duration: kwargs["duration"] = duration
            else: kwargs["speed"] = speed
            
            audio = self.model.generate(**kwargs)
            if op_dialog.cancel_flag: return
            self.audio_data = audio[0]
        except Exception as e:
            if not op_dialog.cancel_flag:
                wx.CallAfter(self.Log, self._("msg_error") + str(e))
"""
code = code.replace("    def OnGenDesign(self, event):", setupauto + "\n    def OnGenDesign(self, event):")

# 3. Add duration parameter to SetupAdvTab
setupadv_old = """        self.spin_speed.SetToolTip(lbl_speed)
        for child in self.spin_speed.GetChildren(): child.SetName(lbl_speed)
        vbox.Add(self.spin_speed, 0, wx.ALL, 5)
        
        lbl_denoise = self._("denoise")"""
        
setupadv_new = """        self.spin_speed.SetToolTip(lbl_speed)
        for child in self.spin_speed.GetChildren(): child.SetName(lbl_speed)
        vbox.Add(self.spin_speed, 0, wx.ALL, 5)
        
        hbox_dur = wx.BoxSizer(wx.HORIZONTAL)
        self.chk_duration = wx.CheckBox(tab, label="Wymuś czas (Duration) w sekundach:")
        self.chk_duration.SetValue(False)
        self.spin_duration = wx.SpinCtrlDouble(tab, value="10.0", min=0.1, max=300.0, inc=0.5)
        hbox_dur.Add(self.chk_duration, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        hbox_dur.Add(self.spin_duration, 0, wx.ALL, 0)
        vbox.Add(hbox_dur, 0, wx.ALL, 5)
        
        lbl_denoise = self._("denoise")"""
code = code.replace(setupadv_old, setupadv_new)

# 4. Update OnGenClone and OnGenDesign to use duration and normalize_text
gen_clone_old = """        speed = self.spin_speed.GetValue()"""
gen_clone_new = """        speed = self.spin_speed.GetValue()
        duration = self.spin_duration.GetValue() if self.chk_duration.GetValue() else None
        norm_txt = self.cfg.get("normalize_text", False)"""
code = code.replace(gen_clone_old, gen_clone_new)

gen_clone_worker_old = """            audio = self.model.generate(text=text, language=lang, speed=speed, generation_config=gen_config, voice_clone_prompt=prompt)"""
gen_clone_worker_new = """            kwargs = {"text": text, "generation_config": gen_config, "voice_clone_prompt": prompt, "normalize_text": norm_txt}
            if lang: kwargs["language"] = lang
            if duration: kwargs["duration"] = duration
            else: kwargs["speed"] = speed
            audio = self.model.generate(**kwargs)"""
code = code.replace(gen_clone_worker_old, gen_clone_worker_new)

gen_design_worker_old = """            audio = self.model.generate(text=text, language=lang, speed=speed, instruct=instruct, generation_config=gen_config)"""
gen_design_worker_new = """            kwargs = {"text": text, "instruct": instruct, "generation_config": gen_config, "normalize_text": norm_txt}
            if lang: kwargs["language"] = lang
            if duration: kwargs["duration"] = duration
            else: kwargs["speed"] = speed
            audio = self.model.generate(**kwargs)"""
code = code.replace(gen_design_worker_old, gen_design_worker_new)

# Modify runoperation signatures
code = code.replace("self._GenCloneWorker, text, lang, speed, prompt", "self._GenCloneWorker, text, lang, speed, duration, norm_txt, prompt")
code = code.replace("def _GenCloneWorker(self, op_dialog, text, lang, speed, prompt):", "def _GenCloneWorker(self, op_dialog, text, lang, speed, duration, norm_txt, prompt):")

code = code.replace("self._GenDesignWorker, text, lang, instruct, speed", "self._GenDesignWorker, text, lang, instruct, speed, duration, norm_txt")
code = code.replace("def _GenDesignWorker(self, op_dialog, text, lang, instruct, speed):", "def _GenDesignWorker(self, op_dialog, text, lang, instruct, speed, duration, norm_txt):")


# 5. Add Menu Bar with Tags Help
menubar_old = """        self.panel = wx.Panel(self)
        self.main_vbox = wx.BoxSizer(wx.VERTICAL)"""
menubar_new = """        
        menubar = wx.MenuBar()
        help_menu = wx.Menu()
        item_tags = help_menu.Append(wx.ID_ANY, "Tagi i Symbole (Tags/Symbols)", "Wyświetl dostępne tagi mowy")
        self.Bind(wx.EVT_MENU, self.OnShowTags, item_tags)
        menubar.Append(help_menu, "Pomoc (Help)")
        self.SetMenuBar(menubar)
        
        self.panel = wx.Panel(self)
        self.main_vbox = wx.BoxSizer(wx.VERTICAL)"""
code = code.replace(menubar_old, menubar_new)

ontags = """
    def OnShowTags(self, event):
        msg = \"\"\"Dostępne specjalne tagi do wpisania w treść tekstu:

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
        wx.MessageBox(msg, "Dostępne Tagi", wx.OK | wx.ICON_INFORMATION)
"""

code = code.replace("def main():", ontags + "\ndef main():")

# 6. Apply asr_model_name in LoadModelWorker
load_old = """self.model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=device, dtype=torch.float16, load_asr=True)"""
load_new = """
            asr_name = self.cfg.get("asr_model_name", "")
            kwargs = {"device_map": device, "dtype": torch.float16, "load_asr": True}
            if asr_name: kwargs["asr_model_name"] = asr_name
            self.model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", **kwargs)
"""
code = code.replace(load_old, load_new)

with codecs.open("wx_app.py", "w", encoding="utf-8") as f:
    f.write(code)
