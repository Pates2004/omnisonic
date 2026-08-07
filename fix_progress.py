import re
import io
import json
import codecs

# 1. Update Lang Files
pl_add = {
    "fake_progress_lbl": "Pokaż sztuczne procenty paska postępu"
}
en_add = {
    "fake_progress_lbl": "Show fake progress bar percentages"
}

for lng_file, strings in [("langs/pl.lng", pl_add), ("langs/en.lng", en_add)]:
    try:
        with codecs.open(lng_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in strings.items():
            data[k] = v
        with codecs.open(lng_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"Error saving {lng_file}: {e}")

# 2. Update Settings.json Defaults (not strictly necessary but good)
try:
    with codecs.open("settings.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if "fake_progress_numbers" not in cfg:
        cfg["fake_progress_numbers"] = False
    with codecs.open("settings.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)
except:
    pass

# 3. Update wx_app.py
with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Add to LoadBasicConfig
code = code.replace(
    '"ai_speed": 1.0, "ai_denoise": True}',
    '"ai_speed": 1.0, "ai_denoise": True, "fake_progress_numbers": False}'
)

# Replace Bind(wx.EVT_TIMER...) in StartupSplash and OperationDialog
code = re.sub(
    r'self\.dialog\.Bind\(wx\.EVT_TIMER, lambda e: gauge\.SetValue\(\(gauge\.GetValue\(\) \+ 5\) % 101\), timer\)',
    r'self.dialog.Bind(wx.EVT_TIMER, lambda e: gauge.SetValue((gauge.GetValue() + 5) % 101) if self.cfg.get("fake_progress_numbers", False) else gauge.Pulse(), timer)',
    code
)

# Replace OmniVoiceFrame.OnProgTimer
on_prog_old = """    def OnProgTimer(self, event):
        self.gauge.SetValue((self.gauge.GetValue() + 2) % 101)"""
on_prog_new = """    def OnProgTimer(self, event):
        if self.cfg.get("fake_progress_numbers", False):
            self.gauge.SetValue((self.gauge.GetValue() + 2) % 101)
        else:
            self.gauge.Pulse()"""
code = code.replace(on_prog_old, on_prog_new)

# Replace DownloadDialog.OnTimer
dl_timer_old = """    def OnTimer(self, event):
        self.gauge.Pulse()"""
dl_timer_new = """    def OnTimer(self, event):
        app = wx.GetApp()
        cfg = app.GetTopWindow().cfg if app and app.GetTopWindow() and hasattr(app.GetTopWindow(), "cfg") else {}
        if cfg.get("fake_progress_numbers", False):
            self.gauge.SetValue((self.gauge.GetValue() + 5) % 101)
        else:
            self.gauge.Pulse()"""
code = code.replace(dl_timer_old, dl_timer_new)

# Add Setting to SettingsDialog
# Find where chk_show_progress is added
opts_old = """            self.chk_show_progress = wx.CheckBox(tab_opts, label=self._("show_progress_lbl"))
            self.chk_show_progress.SetValue(self.cfg.get("show_progress", True))
            vbox_opts.Add(self.chk_show_progress, 0, wx.ALL | wx.EXPAND, 5)"""
opts_new = """            self.chk_show_progress = wx.CheckBox(tab_opts, label=self._("show_progress_lbl"))
            self.chk_show_progress.SetValue(self.cfg.get("show_progress", True))
            vbox_opts.Add(self.chk_show_progress, 0, wx.ALL | wx.EXPAND, 5)
            
            self.chk_fake_progress = wx.CheckBox(tab_opts, label=self._("fake_progress_lbl"))
            self.chk_fake_progress.SetValue(self.cfg.get("fake_progress_numbers", False))
            vbox_opts.Add(self.chk_fake_progress, 0, wx.ALL | wx.EXPAND, 5)"""
code = code.replace(opts_old, opts_new)

# Add to OnSave
save_old = """            self.cfg["show_progress"] = self.chk_show_progress.GetValue()"""
save_new = """            self.cfg["show_progress"] = self.chk_show_progress.GetValue()
            self.cfg["fake_progress_numbers"] = self.chk_fake_progress.GetValue()"""
code = code.replace(save_old, save_new)

# Add to OnResetApp
reset_old = """            self.chk_show_progress.SetValue(True)"""
reset_new = """            self.chk_show_progress.SetValue(True)
            self.chk_fake_progress.SetValue(False)"""
code = code.replace(reset_old, reset_new)


with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
