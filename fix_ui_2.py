import io
import re

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Remove Presets tab from notebook
notebook_old = """        notebook.AddPage(tab_clone, self._("tab_clone"))
        notebook.AddPage(tab_design, self._("tab_design"))
        notebook.AddPage(tab_presets, self._("tab_presets"))
        notebook.AddPage(tab_adv, self._("tab_adv"))"""
notebook_new = """        notebook.AddPage(tab_clone, self._("tab_clone"))
        notebook.AddPage(tab_design, self._("tab_design"))
        notebook.AddPage(tab_adv, self._("tab_adv"))"""
code = code.replace(notebook_old, notebook_new)

notebook_setup_old = """        self.SetupCloneTab(tab_clone)
        self.SetupDesignTab(tab_design)
        self.SetupPresetsTab(tab_presets)
        self.SetupAdvTab(tab_adv)"""
notebook_setup_new = """        self.SetupCloneTab(tab_clone)
        self.SetupDesignTab(tab_design)
        self.SetupAdvTab(tab_adv)"""
code = code.replace(notebook_setup_old, notebook_setup_new)

tab_create_old = """        tab_clone = wx.Panel(notebook)
        tab_design = wx.Panel(notebook)
        tab_presets = wx.Panel(notebook)
        tab_adv = wx.Panel(notebook)"""
tab_create_new = """        tab_clone = wx.Panel(notebook)
        tab_design = wx.Panel(notebook)
        tab_adv = wx.Panel(notebook)"""
code = code.replace(tab_create_old, tab_create_new)

# 2. Update SetupCloneTab
clone_presets_old = """        hbox_p = wx.BoxSizer(wx.HORIZONTAL)
        self.combo_presets = wx.ComboBox(tab, style=wx.CB_READONLY)
        btn_refresh = wx.Button(tab, label=self._("refresh"))
        btn_refresh.Bind(wx.EVT_BUTTON, lambda e: self.RefreshPresets())
        hbox_p.Add(self.combo_presets, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_p.Add(btn_refresh, 0, wx.EXPAND, 0)
        vbox.Add(hbox_p, 0, wx.EXPAND | wx.ALL, 5)"""
clone_presets_new = """        hbox_p = wx.BoxSizer(wx.HORIZONTAL)
        self.combo_presets = wx.ComboBox(tab, style=wx.CB_READONLY)
        self.combo_presets.Bind(wx.EVT_KEY_DOWN, self.OnPresetKeyDown)
        
        btn_refresh = wx.Button(tab, label=self._("refresh"))
        btn_refresh.Bind(wx.EVT_BUTTON, lambda e: self.RefreshPresets())
        
        btn_del_preset = wx.Button(tab, label=self._("btn_del_preset"))
        btn_del_preset.Bind(wx.EVT_BUTTON, self.OnDelPreset)
        
        btn_del_all = wx.Button(tab, label=self._("btn_del_all_presets"))
        btn_del_all.Bind(wx.EVT_BUTTON, self.OnDelAllPresets)
        
        hbox_p.Add(self.combo_presets, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_p.Add(btn_refresh, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_p.Add(btn_del_preset, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_p.Add(btn_del_all, 0, wx.EXPAND, 0)
        vbox.Add(hbox_p, 0, wx.EXPAND | wx.ALL, 5)"""
code = code.replace(clone_presets_old, clone_presets_new)

clone_audio_old = """        hbox_ref.Add(self.clone_ref_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(btn_browse, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_play_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_rec_ref, 0, wx.EXPAND, 0)
        vbox.Add(hbox_ref, 0, wx.EXPAND | wx.ALL, 5)"""
clone_audio_new = """        hbox_ref.Add(self.clone_ref_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(btn_browse, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_play_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_rec_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        
        self.btn_save_preset = wx.Button(tab, label=self._("btn_save_preset_clone"))
        self.btn_save_preset.Bind(wx.EVT_BUTTON, self.OnSavePresetPrompt)
        hbox_ref.Add(self.btn_save_preset, 0, wx.EXPAND, 0)
        vbox.Add(hbox_ref, 0, wx.EXPAND | wx.ALL, 5)"""
code = code.replace(clone_audio_old, clone_audio_new)

# 3. Remove SetupPresetsTab completely
code = re.sub(r'    def SetupPresetsTab\(self, tab\):.*?    def SetupAdvTab\(self, tab\):', r'    def SetupAdvTab(self, tab):', code, flags=re.DOTALL)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
