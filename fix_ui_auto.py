import io

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()
    
# Fix unlabelled SpinCtrls and add Auto tab to notebook
old_initui = """        self.notebook.AddPage(self.tab_clone, self._("tab_clone"))
        self.notebook.AddPage(self.tab_design, self._("tab_design"))
        self.notebook.AddPage(self.tab_adv, self._("tab_adv"))
        
        self.SetupCloneTab(self.tab_clone)
        self.SetupDesignTab(self.tab_design)
        self.SetupAdvTab(self.tab_adv)"""

new_initui = """        self.tab_auto = wx.Panel(self.notebook)
        
        self.notebook.AddPage(self.tab_clone, self._("tab_clone"))
        self.notebook.AddPage(self.tab_design, self._("tab_design"))
        self.notebook.AddPage(self.tab_auto, self._("tab_auto"))
        self.notebook.AddPage(self.tab_adv, self._("tab_adv"))
        
        self.SetupCloneTab(self.tab_clone)
        self.SetupDesignTab(self.tab_design)
        self.SetupAutoTab(self.tab_auto)
        self.SetupAdvTab(self.tab_adv)"""

code = code.replace(old_initui, new_initui)

old_menu = """        menubar.Append(progMenu, self._("menu_prog"))
        self.SetMenuBar(menubar)"""

new_menu = """        menubar.Append(progMenu, self._("menu_prog"))
        
        helpMenu = wx.Menu()
        item_tags = helpMenu.Append(wx.ID_ANY, self._("menu_help_tags"))
        self.Bind(wx.EVT_MENU, self.OnShowTags, item_tags)
        menubar.Append(helpMenu, self._("menu_help"))
        
        self.SetMenuBar(menubar)"""

code = code.replace(old_menu, new_menu)

# Fix audio player labels
old_audio = """        hbox_audio = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_play = wx.Button(self.panel, label=self._("play"))
        self.btn_play.Bind(wx.EVT_BUTTON, self.OnPlayAudio)
        self.btn_play.Disable()
        
        self.btn_save = wx.Button(self.panel, label=self._("save"))
        self.btn_save.Bind(wx.EVT_BUTTON, self.OnSaveAudio)
        self.btn_save.Disable()"""
        
new_audio = """        hbox_audio = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_play = wx.Button(self.panel, label=self._("play"))
        self.btn_play.Bind(wx.EVT_BUTTON, self.OnPlayAudio)
        self.btn_play.Disable()
        
        self.btn_pause = wx.Button(self.panel, label=self._("btn_pause"))
        self.btn_pause.Bind(wx.EVT_BUTTON, self.OnPauseAudio)
        self.btn_pause.Disable()
        
        self.btn_save = wx.Button(self.panel, label=self._("save"))
        self.btn_save.Bind(wx.EVT_BUTTON, self.OnSaveAudio)
        self.btn_save.Disable()"""

# But first check if btn_pause is in langs
code = code.replace(old_audio, new_audio)
code = code.replace("hbox_audio.Add(self.btn_save, 1, wx.EXPAND, 0)", "hbox_audio.Add(self.btn_pause, 1, wx.EXPAND | wx.RIGHT, 5)\n        hbox_audio.Add(self.btn_save, 1, wx.EXPAND, 0)")

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
