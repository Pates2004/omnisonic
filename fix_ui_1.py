import io
import re
import codecs
import json

# 1. Update Lang Files
pl_add = {
    "fake_progress_lbl": "Pokazuj dostępny symulowany postęp paska postępu",
    "btn_save_preset_clone": "Zapisz jako preset",
    "prompt_preset_name": "Podaj nazwę dla nowego presetu:",
    "preset_name_title": "Zapisz preset",
    "btn_del_preset": "Usuń preset",
    "btn_del_all_presets": "Usuń wszystkie presety",
    "warn_del_preset": "Czy na pewno chcesz skasować preset {name}?\nTej akcji nie można cofnąć!",
    "warn_del_all": "Czy na pewno chcesz usunąć wszystkie presety?\nTej akcji nie można cofnąć!",
    "warn_no_show": "Nie pokazuj więcej tego ostrzeżenia",
    "msg_no_preset_sel": "Nie wybrano presetu.",
    "msg_presets_deleted": "Usunięto wszystkie presety."
}

en_add = {
    "fake_progress_lbl": "Show simulated accessible progress bar",
    "btn_save_preset_clone": "Save as preset",
    "prompt_preset_name": "Enter name for the new preset:",
    "preset_name_title": "Save preset",
    "btn_del_preset": "Delete preset",
    "btn_del_all_presets": "Delete all presets",
    "warn_del_preset": "Are you sure you want to delete preset {name}?\nThis cannot be undone!",
    "warn_del_all": "Are you sure you want to delete all presets?\nThis cannot be undone!",
    "warn_no_show": "Do not show this warning again",
    "msg_no_preset_sel": "No preset selected.",
    "msg_presets_deleted": "All presets deleted."
}

for lng_file, strings in [("langs/pl.lng", pl_add), ("langs/en.lng", en_add)]:
    try:
        with codecs.open(lng_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in strings.items():
            data[k] = v
        with codecs.open(lng_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except:
        pass

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# 2. Add duration elements to SetupAdvTab
adv_tab_search = """        vbox.Add(self.chk_denoise, 0, wx.ALL, 5)
        tab.SetSizer(vbox)"""
adv_tab_replace = """        vbox.Add(self.chk_denoise, 0, wx.ALL, 5)
        
        lbl_dur = self._("duration_lbl")
        self.chk_duration = wx.CheckBox(tab, label=lbl_dur)
        self.chk_duration.SetName(lbl_dur)
        self.chk_duration.SetValue(self.cfg.get("use_duration", False))
        vbox.Add(self.chk_duration, 0, wx.ALL, 5)
        
        self.spin_duration = wx.SpinCtrlDouble(tab, value=str(self.cfg.get("duration_val", 5.0)), min=0.1, max=100.0, inc=0.5)
        self.spin_duration.SetName(lbl_dur)
        self.spin_duration.SetToolTip(lbl_dur)
        for child in self.spin_duration.GetChildren(): child.SetName(lbl_dur)
        vbox.Add(self.spin_duration, 0, wx.ALL, 5)
        
        tab.SetSizer(vbox)"""
code = code.replace(adv_tab_search, adv_tab_replace)

# 3. Add to OnSave so it remembers duration settings
save_search = """            self.cfg["clean_temp"] = self.chk_clean_temp.GetValue()"""
save_replace = """            self.cfg["clean_temp"] = self.chk_clean_temp.GetValue()
            if hasattr(self.GetParent(), 'chk_duration'):
                self.cfg["use_duration"] = self.GetParent().chk_duration.GetValue()
                self.cfg["duration_val"] = self.GetParent().spin_duration.GetValue()"""
code = code.replace(save_search, save_replace)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
