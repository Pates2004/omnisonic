import wx
import os
import json
import glob
import threading
import ctypes
import sys
import logging

torch = None
np = None
sf = None
sd = None
OmniVoice = None
OmniVoiceGenerationConfig = None
VoiceClonePrompt = None
get_best_device = None

_ALL_LANGUAGES = ["Auto"]

_CATEGORIES = {
    "Gender": ["None", "Male", "Female"],
    "Age": ["None", "Child", "Teenager", "Young Adult", "Middle-aged", "Elderly"],
    "Pitch": ["None", "Very Low Pitch", "Low Pitch", "Moderate Pitch", "High Pitch", "Very High Pitch"],
    "Style": ["None", "Whisper"],
    "Accent": ["None", "American Accent", "Australian Accent", "British Accent", "Chinese Accent", "Canadian Accent", "Indian Accent", "Korean Accent", "Portuguese Accent", "Russian Accent", "Japanese Accent"],
}

LANGS_DIR = "langs"
CONFIG_FILE = "settings.json"
PRESETS_DIR = "presets"

def LoadLocales():
    locales = {}
    os.makedirs(LANGS_DIR, exist_ok=True)
    lang_files = glob.glob(os.path.join(LANGS_DIR, "*.lng"))
    for f in lang_files:
        try:
            with open(f, "r", encoding="utf-8") as file:
                data = json.load(file)
                lang_code = os.path.splitext(os.path.basename(f))[0]
                locales[lang_code] = data
        except:
            pass
    if not locales:
        locales["en"] = {"title": "OmniVoice", "msg_error": "Error: ", "btn_save": "Save", "btn_cancel": "Cancel", "first_run_title": "Setup", "lang_lbl": "Lang", "theme_lbl": "Theme", "console_lbl": "Console", "font_size_lbl": "Font size", "warn_exit_lbl": "Warn on exit", "exit_confirm": "Exit?", "theme_light": "Light", "theme_dark": "Dark", "lang_name": "English (en)", "close_warn": "Exit?", "close_busy": "Busy. Exit?", "info_title": "Info", "warning_title": "Warn", "error_title": "Error", "startup_title": "Starting...", "startup_msg": "Loading...", "op_load_title": "Wait", "op_load_msg": "Loading...", "op_unload_title": "Wait", "op_unload_msg": "Unloading...", "op_gen_title": "Wait", "op_gen_msg": "Generating...", "op_preset_title": "Wait", "op_preset_msg": "Saving..."}
    return locales

LOCALE = LoadLocales()

def LoadBasicConfig():
    cfg = {"language": "en", "theme": "light", "show_console": False, "close_console_on_exit": True, "force_splash": False, "show_progress": True, "use_native_dialogs": False, "validate_components": False, "first_run_done": False, "font_size": 10, "warn_exit": True, "remember_ai_settings": True, "clean_temp": True, "confirm_success": False, "ai_steps": 32, "ai_cfg": 2.0, "ai_speed": 1.0, "ai_denoise": True, "fake_progress_numbers": False}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except:
            pass
    if cfg["language"] not in LOCALE and LOCALE:
        cfg["language"] = list(LOCALE.keys())[0]
    return cfg

def SaveBasicConfig(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)

class StartupSplash:
    def __init__(self, parent, cfg):
        self.cfg = cfg
        self.parent = parent
        lang = cfg.get("language", "en")
        self._ = lambda k: LOCALE.get(lang, LOCALE.get("en", {})).get(k, k)
        self.finished = False

    def ShowModal(self):
        use_native = self.cfg.get("use_native_dialogs", False)
        title = self._("startup_title")
        msg = self._("startup_msg")
        
        if use_native:
            self.dialog = wx.ProgressDialog(title, msg or "ProszĂ„â„˘ czekaĂ„â€ˇ...", maximum=100, parent=self.parent, style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_SMOOTH)
            threading.Thread(target=self.DoHeavyImports, daemon=True).start()
            while not self.finished:
                cont, skip = self.dialog.Update(self.dialog.GetValue() + 1 if self.dialog.GetValue() < 100 else 0)
                if not cont:
                    dlg = wx.MessageDialog(self.dialog, self._("close_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                    if dlg.ShowModal() == wx.ID_YES:
                        self.dialog.Destroy()
                        import sys
                        sys.exit(0)
                    else:
                        self.dialog.Destroy()
                        self.dialog = wx.ProgressDialog(title, msg or "ProszĂ„â„˘ czekaĂ„â€ˇ...", maximum=100, parent=self.parent, style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_SMOOTH)
                wx.MilliSleep(50)
                wx.GetApp().Yield()
            self.dialog.Destroy()
            return wx.ID_OK
        else:
            self.dialog = wx.Dialog(self.parent, title=title, size=(400, 150))
            panel = wx.Panel(self.dialog)
            vbox = wx.BoxSizer(wx.VERTICAL)
            lbl = wx.StaticText(panel, label=msg)
            vbox.Add(lbl, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 15)
            gauge = wx.Gauge(panel, range=100)
            vbox.Add(gauge, 0, wx.ALL | wx.EXPAND, 10)
            btn = wx.Button(panel, label=self._("btn_cancel"))
            
            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("close_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    import sys
                    sys.exit(0)
                else:
                    import wx
                    if hasattr(wx, "CloseEvent") and isinstance(evt, wx.CloseEvent):
                        evt.Veto()
            btn.Bind(wx.EVT_BUTTON, OnCancel)
            self.dialog.Bind(wx.EVT_CLOSE, OnCancel)
            vbox.Add(btn, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 5)
            panel.SetSizer(vbox)
            self.dialog.Centre()
            
            timer = wx.Timer(self.dialog)
            self.dialog.Bind(wx.EVT_TIMER, lambda e: gauge.SetValue((gauge.GetValue() + 5) % 101) if self.cfg.get("fake_progress_numbers", False) else gauge.Pulse(), timer)
            timer.Start(100)
            
            threading.Thread(target=self.DoHeavyImports, daemon=True).start()
            res = self.dialog.ShowModal()
            timer.Stop()
            self.dialog.Destroy()
            return res
            
    def DoHeavyImports(self):
        global torch, np, sf, sd, OmniVoice, OmniVoiceGenerationConfig, VoiceClonePrompt, get_best_device, _ALL_LANGUAGES
        try:
            import soundfile as _sf
            sf = _sf
            import sounddevice as _sd
            sd = _sd
            import numpy as _np
            np = _np
            import torch as _torch
            torch = _torch
            from omnivoice import OmniVoice as _OV, OmniVoiceGenerationConfig as _OVC, VoiceClonePrompt as _VCP
            OmniVoice = _OV
            OmniVoiceGenerationConfig = _OVC
            VoiceClonePrompt = _VCP
            from omnivoice.utils.common import get_best_device as _gbd
            get_best_device = _gbd
            from omnivoice.utils.lang_map import LANG_NAMES, lang_display_name
            
            langs = ["Auto"] + sorted(lang_display_name(n) for n in LANG_NAMES)
            _ALL_LANGUAGES.clear()
            _ALL_LANGUAGES.extend(langs)
        except Exception as e:
            pass
            
        if not self.cfg.get("use_native_dialogs", False):
            wx.CallAfter(self.dialog.EndModal, wx.ID_OK)
        else:
            self.finished = True

class OperationDialog:
    def __init__(self, parent, cfg, title_key, msg_key, worker_func, *args):
        self.parent = parent
        self.cfg = cfg
        lang = cfg.get("language", "en")
        self._ = lambda k: LOCALE.get(lang, LOCALE.get("en", {})).get(k, k)
        
        self.title = self._(title_key)
        self.msg = self._(msg_key)
        self.worker_func = worker_func
        self.args = args
        self.finished = False
        self.cancel_flag = False

    def ShowModal(self):
        use_native = self.cfg.get("use_native_dialogs", False)
        
        if use_native:
            self.dialog = wx.ProgressDialog(self.title, self.msg or "Trwa operacja...", maximum=100, parent=self.parent, style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_SMOOTH)
            threading.Thread(target=self._run_thread_native, daemon=True).start()
            while not self.finished:
                cont, skip = self.dialog.Update(self.dialog.GetValue() + 1 if self.dialog.GetValue() < 100 else 0)
                if not cont:
                    dlg = wx.MessageDialog(self.dialog, self._("stop_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                    if dlg.ShowModal() == wx.ID_YES:
                        self.cancel_flag = True
                        break
                    else:
                        self.dialog.Destroy()
                        self.dialog = wx.ProgressDialog(self.title, self.msg or "Trwa operacja...", maximum=100, parent=self.parent, style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_SMOOTH)
                wx.MilliSleep(50)
                wx.GetApp().Yield()
            self.dialog.Destroy()
            return not self.cancel_flag
        else:
            self.dialog = wx.Dialog(self.parent, title=self.title, size=(400, 150))
            panel = wx.Panel(self.dialog)
            vbox = wx.BoxSizer(wx.VERTICAL)
            lbl = wx.StaticText(panel, label=self.msg)
            vbox.Add(lbl, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 15)
            gauge = wx.Gauge(panel, range=100)
            vbox.Add(gauge, 0, wx.ALL | wx.EXPAND, 10)
            btn = wx.Button(panel, label=self._("btn_cancel"))
            
            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("stop_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    self.cancel_flag = True
                else:
                    import wx
                    if hasattr(wx, "CloseEvent") and isinstance(evt, wx.CloseEvent):
                        evt.Veto()
            btn.Bind(wx.EVT_BUTTON, OnCancel)
            self.dialog.Bind(wx.EVT_CLOSE, OnCancel)
            vbox.Add(btn, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 5)
            panel.SetSizer(vbox)
            self.dialog.Centre()
            
            timer = wx.Timer(self.dialog)
            self.dialog.Bind(wx.EVT_TIMER, lambda e: gauge.SetValue((gauge.GetValue() + 5) % 101) if self.cfg.get("fake_progress_numbers", False) else gauge.Pulse(), timer)
            timer.Start(100)
            
            threading.Thread(target=self._run_thread_custom, daemon=True).start()
            self.dialog.ShowModal()
            timer.Stop()
            self.dialog.Destroy()
            return not self.cancel_flag

    def _run_thread_native(self):
        try:
            self.worker_func(self, *self.args)
        finally:
            self.finished = True
            
    def _run_thread_custom(self):
        try:
            self.worker_func(self, *self.args)
        finally:
            if not self.cancel_flag:
                wx.CallAfter(self.dialog.EndModal, wx.ID_OK)
            else:
                wx.CallAfter(self.dialog.EndModal, wx.ID_CANCEL)

class DownloadDialog(wx.Dialog):
    def __init__(self, parent, title, label, repo_id, lang_func):
        super().__init__(parent, title=title, size=(400, 150))
        self._ = lang_func
        self.repo_id = repo_id
        
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.lbl = wx.StaticText(self, label=label)
        vbox.Add(self.lbl, 0, wx.ALL | wx.EXPAND, 10)
        
        self.gauge = wx.Gauge(self, range=100)
        vbox.Add(self.gauge, 0, wx.ALL | wx.EXPAND, 10)
        
        self.btn_cancel = wx.Button(self, label=self._("btn_cancel"))
        self.btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        vbox.Add(self.btn_cancel, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(vbox)
        self.Bind(wx.EVT_CLOSE, self.OnCancel)
        
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnTimer, self.timer)
        self.timer.Start(50)
        
        self.cancel_flag = False
        
        import threading
        self.t = threading.Thread(target=self._dl_worker)
        self.t.daemon = True
        self.t.start()

    def OnTimer(self, event):
        app = wx.GetApp()
        cfg = app.GetTopWindow().cfg if app and app.GetTopWindow() and hasattr(app.GetTopWindow(), "cfg") else {}
        if cfg.get("fake_progress_numbers", False):
            self.gauge.SetValue((self.gauge.GetValue() + 5) % 101)
        else:
            self.gauge.Pulse()
        if not self.t.is_alive() and not self.cancel_flag:
            self.EndModal(wx.ID_OK)

    def OnCancel(self, event):
        msg = self._("cancel_dl_prompt")
        title = self._("cancel_title")
        if wx.MessageBox(msg, title, wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.cancel_flag = True
            self.timer.Stop()
            self.EndModal(wx.ID_CANCEL)
        else:
            import wx
            if isinstance(event, wx.CloseEvent):
                event.Veto()

    def _dl_worker(self):
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=self.repo_id)
        except Exception as e:
            wx.CallAfter(wx.MessageBox, str(e), self._("error_title"), wx.OK | wx.ICON_ERROR)

class SettingsDialog(wx.Dialog):
    def __init__(self, parent, is_first_run=False, current_cfg=None):
        self.cfg = current_cfg or LoadBasicConfig()
        self.is_first_run = is_first_run
        self.lang = self.cfg.get("language", "pl")
        title = self._("first_run_title") if is_first_run else "Ustawienia / Settings"
        super(SettingsDialog, self).__init__(parent, title=title, size=(450, 450))
        
        self.InitUI()
        self.Centre()
        
    def _(self, key):
        return LOCALE.get(self.lang, LOCALE.get("en", {})).get(key, key)
        
    def InitUI(self):
        panel = wx.Panel(self)
        vbox_main = wx.BoxSizer(wx.VERTICAL)
        
        if self.is_first_run:
            lbl = wx.StaticText(panel, label=self._("first_run_msg"))
            vbox_main.Add(lbl, 0, wx.ALL | wx.EXPAND, 10)
            
        notebook = wx.Notebook(panel)
        tab_app = wx.Panel(notebook)
        
        notebook.AddPage(tab_app, self._("tab_appearance"))
        if not self.is_first_run:
            tab_sys = wx.Panel(notebook)
            tab_opts = wx.Panel(notebook)
            notebook.AddPage(tab_sys, self._("tab_system"))
            notebook.AddPage(tab_opts, self._("tab_ai_opts"))
            
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
            
            wx.StaticText(tab_sys, label=self._("preset_disp_lbl"))
            self.cb_preset_disp = wx.ComboBox(tab_sys, choices=[self._("disp_name"), self._("disp_path"), self._("disp_both")], style=wx.CB_READONLY)
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
        btn_cancel = wx.Button(panel, label=self._("btn_cancel"))
        
        btn_ok.Bind(wx.EVT_BUTTON, self.OnSave)
        btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)
        
        hbox.Add(btn_ok, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox.Add(btn_cancel, 1, wx.EXPAND, 0)
        
        vbox_main.Add(hbox, 0, wx.ALL | wx.EXPAND, 5)
        
        panel.SetSizer(vbox_main)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        
    def OnResetAI(self, event):
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
            wx.MessageBox(self._("reset_ok"), self._("info_title"), wx.OK | wx.ICON_INFORMATION)

    def OnResetApp(self, event):
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
            wx.MessageBox(self._("reset_ok"), self._("info_title"), wx.OK | wx.ICON_INFORMATION)

    def OnCleanTemp(self, event):
        temp_files = ["recorded_ref.wav"]
        count = 0
        freed_bytes = 0
        
        for f in temp_files:
            path = os.path.abspath(f)
            if os.path.exists(path):
                try:
                    freed_bytes += os.path.getsize(path)
                    os.remove(path)
                    count += 1
                except:
                    pass
                    
        if count > 0:
            freed_mb = freed_bytes / (1024 * 1024)
            msg = self._("clean_stats").replace("{count}", str(count)).replace("{mb}", str(round(freed_mb, 2)))
            wx.MessageBox(msg, self._("success_title"), wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox(self._("clean_none"), self._("success_title"), wx.OK | wx.ICON_INFORMATION)

    def OnSave(self, event):
        self.lang = self.avail_langs[self.cb_lang.GetSelection()]
        self.cfg["language"] = self.lang
        self.cfg["theme"] = "light" if self.cb_theme.GetSelection() == 0 else "dark"
        self.cfg["font_size"] = self.spin_font.GetValue()
        
        if not self.is_first_run:
            self.cfg["show_console"] = self.chk_console.GetValue()
            self.cfg["close_console_on_exit"] = self.chk_close_console.GetValue()
            idx = self.cb_preset_disp.GetSelection()
            self.cfg["preset_display_mode"] = "name" if idx == 0 else ("path" if idx == 1 else "name_path")
            self.cfg["force_splash"] = self.chk_force_splash.GetValue()
            self.cfg["show_progress"] = self.chk_show_progress.GetValue()
            self.cfg["fake_progress_numbers"] = self.chk_fake_progress.GetValue()
            self.cfg["use_native_dialogs"] = self.chk_use_native.GetValue()
            self.cfg["validate_components"] = self.chk_validate.GetValue()
            self.cfg["warn_exit"] = self.chk_warn_exit.GetValue()
            self.cfg["confirm_success"] = self.chk_confirm_success.GetValue()
            self.cfg["remember_ai_settings"] = self.chk_remember_ai.GetValue()
            self.cfg["clean_temp"] = self.chk_clean_temp.GetValue()
            if hasattr(self.GetParent(), 'chk_duration'):
                self.cfg["use_duration"] = self.GetParent().chk_duration.GetValue()
                self.cfg["duration_val"] = self.GetParent().spin_duration.GetValue()
            
        self.cfg["first_run_done"] = True
        if self.is_first_run:
            wx.MessageBox(self._("first_run_success"), self._("info_title"), wx.OK | wx.ICON_INFORMATION)
        self.EndModal(wx.ID_OK)
        
    def OnCancel(self, event):
        self.HandleCancel(event)
        
    def OnClose(self, event):
        self.HandleCancel(event)
        
    def HandleCancel(self, event=None):
        dlg = wx.MessageDialog(self, self._("exit_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            self.EndModal(wx.ID_CANCEL)
        else:
            import wx
            if event and hasattr(wx, "CloseEvent") and isinstance(event, wx.CloseEvent):
                event.Veto()


class OmniVoiceFrame(wx.Frame):
    def __init__(self, cfg, *args, **kw):
        super(OmniVoiceFrame, self).__init__(*args, **kw)
        
        self.cfg = cfg
        self.model = None
        self.audio_data = None
        self.sample_rate = 24000
        self.current_op = None
        
        os.makedirs(PRESETS_DIR, exist_ok=True)
        self.ApplyConsoleState()
        
        self.InitUI()
        self.ApplyTheme()
        self.ApplyFontSize()
        self.SetSize((900, 800))
        self.Centre()
        
        self.Bind(wx.EVT_CLOSE, self.OnCloseWindow)
        
        wx.CallLater(500, self.AutoLoadModel)
        
    def _(self, key):
        return LOCALE.get(self.cfg.get("language", "en"), LOCALE.get("en", {})).get(key, key)
            
    def ApplyConsoleState(self):
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            if self.cfg.get("show_console"):
                ctypes.windll.user32.ShowWindow(hwnd, 5) # SW_SHOW
            else:
                ctypes.windll.user32.ShowWindow(hwnd, 0) # SW_HIDE

    def ApplyTheme(self):
        theme = self.cfg.get("theme", "light")
        bg_color = wx.Colour(40, 40, 40) if theme == "dark" else wx.NullColour
        fg_color = wx.Colour(220, 220, 220) if theme == "dark" else wx.NullColour
        
        if theme == "dark":
            self.SetBackgroundColour(bg_color)
            self.SetForegroundColour(fg_color)
            def color_children(parent):
                for child in parent.GetChildren():
                    if not isinstance(child, (wx.TextCtrl, wx.ComboBox, wx.SpinCtrl, wx.SpinCtrlDouble, wx.Button, wx.Gauge)):
                        child.SetBackgroundColour(bg_color)
                        child.SetForegroundColour(fg_color)
                    color_children(child)
            color_children(self)
        self.Refresh()
        
    def ApplyFontSize(self):
        size = self.cfg.get("font_size", 10)
        font = self.GetFont()
        font.SetPointSize(size)
        self.SetFont(font)
        
        def set_font_children(parent):
            for child in parent.GetChildren():
                child.SetFont(font)
                set_font_children(child)
                
        set_font_children(self)
        self.Layout()
        self.Refresh()
            
    def InitUI(self):
        self.SetTitle(self._("title"))
        
        menubar = wx.MenuBar()
        progMenu = wx.Menu()
        
        item_settings = progMenu.Append(wx.ID_ANY, self._("menu_settings"))
        self.Bind(wx.EVT_MENU, self.OnOpenSettings, item_settings)
        
        item_exit = progMenu.Append(wx.ID_EXIT, self._("menu_exit"))
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), item_exit)
        
        menubar.Append(progMenu, self._("menu_prog"))
        
        helpMenu = wx.Menu()
        item_tags = helpMenu.Append(wx.ID_ANY, self._("menu_help_tags"))
        self.Bind(wx.EVT_MENU, self.OnShowTags, item_tags)
        menubar.Append(helpMenu, self._("menu_help"))
        
        self.SetMenuBar(menubar)
        
        self.panel = wx.Panel(self)
        self.main_vbox = wx.BoxSizer(wx.VERTICAL)
        
        hbox_top = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_toggle_model = wx.Button(self.panel, label=self._("load_model"))
        self.btn_toggle_model.Bind(wx.EVT_BUTTON, self.OnToggleModel)
        
        hbox_top.Add(self.btn_toggle_model, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.main_vbox.Add(hbox_top, 0, wx.EXPAND)
        
        self.notebook = wx.Notebook(self.panel)
        self.tab_clone = wx.Panel(self.notebook)
        self.tab_design = wx.Panel(self.notebook)
        self.tab_adv = wx.Panel(self.notebook)
        
        self.tab_auto = wx.Panel(self.notebook)
        
        self.notebook.AddPage(self.tab_clone, self._("tab_clone"))
        self.notebook.AddPage(self.tab_design, self._("tab_design"))
        self.notebook.AddPage(self.tab_auto, self._("tab_auto"))
        self.notebook.AddPage(self.tab_adv, self._("tab_adv"))
        
        self.SetupCloneTab(self.tab_clone)
        self.SetupDesignTab(self.tab_design)
        self.SetupAutoTab(self.tab_auto)
        self.SetupAdvTab(self.tab_adv)
        
        self.main_vbox.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        
        wx.StaticText(self.panel, label=self._("status"))
        self.status_text = wx.TextCtrl(self.panel, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 80))
        self.main_vbox.Add(self.status_text, 0, wx.EXPAND | wx.ALL, 5)
        
        hbox_prog = wx.BoxSizer(wx.HORIZONTAL)
        self.gauge = wx.Gauge(self.panel, range=100)
        self.btn_stop = wx.Button(self.panel, label=self._("btn_cancel"))
        self.btn_stop.Bind(wx.EVT_BUTTON, self.OnStopOperation)
        self.btn_stop.Disable()
        hbox_prog.Add(self.gauge, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_prog.Add(self.btn_stop, 0, wx.EXPAND, 0)
        self.main_vbox.Add(hbox_prog, 0, wx.EXPAND | wx.ALL, 5)
        
        self.prog_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnProgTimer, self.prog_timer)
        
        hbox_audio = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_play = wx.Button(self.panel, label=self._("play"))
        self.btn_play.Bind(wx.EVT_BUTTON, self.OnPlayAudio)
        self.btn_play.Disable()
        
        self.btn_pause = wx.Button(self.panel, label=self._("btn_pause"))
        self.btn_pause.Bind(wx.EVT_BUTTON, self.OnPauseAudio)
        self.btn_pause.Disable()
        
        self.btn_save = wx.Button(self.panel, label=self._("save"))
        self.btn_save.Bind(wx.EVT_BUTTON, self.OnSaveAudio)
        self.btn_save.Disable()
        
        hbox_audio.Add(self.btn_play, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_audio.Add(self.btn_pause, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_audio.Add(self.btn_save, 1, wx.EXPAND, 0)
        self.main_vbox.Add(hbox_audio, 0, wx.EXPAND | wx.ALL, 5)
        
        self.panel.SetSizer(self.main_vbox)
        self.RefreshPresets()

    def OnProgTimer(self, event):
        if self.cfg.get("fake_progress_numbers", False):
            self.gauge.SetValue((self.gauge.GetValue() + 2) % 101)
        else:
            self.gauge.Pulse()

    def OnStopOperation(self, event):
        if self.current_op:
            dlg = wx.MessageDialog(self, self._("stop_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                self.current_op.cancel_flag = True
                self.Log("Anulowanie... / Canceling...")

    def RunOperation(self, title_key, msg_key, worker_func, *args, success_callback=None):
        if self.cfg.get("show_progress", True):
            dlg = OperationDialog(self, self.cfg, title_key, msg_key, worker_func, *args)
            success = dlg.ShowModal()
            if success and success_callback:
                success_callback()
        else:
            self.Log(self._(msg_key))
            self.current_op = type("DummyOp", (), {"cancel_flag": False, "finished": False})()
            self.btn_stop.Enable()
            self.gauge.SetValue(0)
            self.prog_timer.Start(50)
            
            # Disable generate buttons
            self.btn_gen_clone.Disable()
            self.btn_gen_design.Disable()
            self.btn_save_preset.Disable()
            self.btn_toggle_model.Disable()
            
            def wrapper():
                try:
                    worker_func(self.current_op, *args)
                finally:
                    self.current_op.finished = True
                    wx.CallAfter(self.EndOperation, success_callback)
                    
            threading.Thread(target=wrapper, daemon=True).start()
            
    def EndOperation(self, success_callback):
        self.prog_timer.Stop()
        self.gauge.SetValue(0)
        self.btn_stop.Disable()
        
        self.btn_gen_clone.Enable()
        self.btn_gen_design.Enable()
        self.btn_save_preset.Enable()
        self.btn_toggle_model.Enable()
        
        if not self.current_op.cancel_flag and success_callback:
            success_callback()
        self.current_op = None

    def OnOpenSettings(self, event):
        dlg = SettingsDialog(self, is_first_run=False, current_cfg=self.cfg.copy())
        if dlg.ShowModal() == wx.ID_OK:
            old_lang = self.cfg["language"]
            self.cfg = dlg.cfg
            SaveBasicConfig(self.cfg)
            self.ApplyConsoleState()
            self.ApplyTheme()
            self.ApplyFontSize()
            if old_lang != self.cfg["language"]:
                wx.MessageBox(self._("restart_lang"), self._("info_title"))
        dlg.Destroy()
        
    def OnCloseWindow(self, event):
        if self.current_op and not self.current_op.finished:
            dlg = wx.MessageDialog(self, self._("close_busy"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_NO:
                event.Veto()
                return
            self.current_op.cancel_flag = True
                
        if self.cfg.get("warn_exit", True) and not (self.current_op and not self.current_op.finished):
            dlg = wx.MessageDialog(self, self._("close_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_NO:
                event.Veto()
                return
        
        if self.cfg.get("remember_ai_settings", True):
            if hasattr(self, 'spin_steps'):
                self.cfg["ai_steps"] = self.spin_steps.GetValue()
                self.cfg["ai_cfg"] = self.spin_cfg.GetValue()
                self.cfg["ai_speed"] = self.spin_speed.GetValue()
                self.cfg["ai_denoise"] = self.chk_denoise.GetValue()
            SaveBasicConfig(self.cfg)
            
        if self.cfg.get("clean_temp", True):
            path = os.path.abspath("recorded_ref.wav")
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
        
        if hasattr(self, 'rec_stream'):
            try:
                self.rec_stream.stop()
                self.rec_stream.close()
            except:
                pass

        import sys
        sys.exit(0)

    def SetupCloneTab(self, tab):
        vbox = wx.BoxSizer(wx.VERTICAL)
        wx.StaticText(tab, label=self._("text_to_read"))
        self.clone_text = wx.TextCtrl(tab, style=wx.TE_MULTILINE, size=(-1, 100))
        self.clone_text.SetName(self._("text_to_read"))
        vbox.Add(self.clone_text, 0, wx.EXPAND | wx.ALL, 5)
        wx.StaticText(tab, label=self._("preset_list"))
        hbox_p = wx.BoxSizer(wx.HORIZONTAL)
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
        vbox.Add(hbox_p, 0, wx.EXPAND | wx.ALL, 5)
        wx.StaticText(tab, label=self._("ref_audio"))
        hbox_ref = wx.BoxSizer(wx.HORIZONTAL)
        self.clone_ref_audio = wx.TextCtrl(tab)
        self.clone_ref_audio.SetName(self._("ref_audio"))
        btn_browse = wx.Button(tab, label=self._("browse"))
        btn_browse.Bind(wx.EVT_BUTTON, self.OnBrowseRefAudio)
        
        self.btn_play_ref = wx.Button(tab, label=self._("play_ref"))
        self.btn_play_ref.Bind(wx.EVT_BUTTON, lambda e: self.TogglePlayFile(self.btn_play_ref, self.clone_ref_audio))
        
        self.btn_rec_ref = wx.Button(tab, label=self._("rec_ref"))
        self.btn_rec_ref.Bind(wx.EVT_BUTTON, lambda e: self.ToggleRecord(self.btn_rec_ref, self.clone_ref_audio))
        
        hbox_ref.Add(self.clone_ref_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(btn_browse, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_play_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_rec_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        
        self.btn_save_preset = wx.Button(tab, label=self._("btn_save_preset_clone"))
        self.btn_save_preset.Bind(wx.EVT_BUTTON, self.OnSavePresetPrompt)
        hbox_ref.Add(self.btn_save_preset, 0, wx.EXPAND, 0)
        vbox.Add(hbox_ref, 0, wx.EXPAND | wx.ALL, 5)
        wx.StaticText(tab, label=self._("ref_text"))
        self.clone_ref_text = wx.TextCtrl(tab)
        self.clone_ref_text.SetName(self._("ref_text"))
        vbox.Add(self.clone_ref_text, 0, wx.EXPAND | wx.ALL, 5)
        wx.StaticText(tab, label=self._("lang_select"))
        self.clone_lang = wx.ComboBox(tab, choices=_ALL_LANGUAGES, style=wx.CB_READONLY)
        self.clone_lang.SetName(self._("lang_select"))
        def_clone_lang = self.cfg.get("clone_lang", "Auto") if self.cfg.get("remember_ai_settings", True) else "Auto"
        self.clone_lang.SetValue(def_clone_lang)
        vbox.Add(self.clone_lang, 0, wx.EXPAND | wx.ALL, 5)
        self.btn_gen_clone = wx.Button(tab, label=self._("gen_clone"))
        self.btn_gen_clone.Bind(wx.EVT_BUTTON, self.OnGenClone)
        vbox.Add(self.btn_gen_clone, 0, wx.EXPAND | wx.ALL, 5)
        tab.SetSizer(vbox)

    def SetupDesignTab(self, tab):
        vbox = wx.BoxSizer(wx.VERTICAL)
        wx.StaticText(tab, label=self._("text_to_read"))
        self.design_text = wx.TextCtrl(tab, style=wx.TE_MULTILINE, size=(-1, 100))
        self.design_text.SetName(self._("text_to_read"))
        vbox.Add(self.design_text, 0, wx.EXPAND | wx.ALL, 5)
        wx.StaticText(tab, label=self._("lang_select"))
        self.design_lang = wx.ComboBox(tab, choices=_ALL_LANGUAGES, style=wx.CB_READONLY)
        self.design_lang.SetName(self._("lang_select"))
        def_design_lang = self.cfg.get("design_lang", "Auto") if self.cfg.get("remember_ai_settings", True) else "Auto"
        self.design_lang.SetValue(def_design_lang)
        vbox.Add(self.design_lang, 0, wx.EXPAND | wx.ALL, 5)
        self.design_combos = []
        for cat, choices in _CATEGORIES.items():
            hbox = wx.BoxSizer(wx.HORIZONTAL)
            cat_trans = self._("cat_" + cat)
            label = wx.StaticText(tab, label=f"{cat_trans}:", size=(150, -1))
            choices_trans = [self._("val_" + c) for c in choices]
            combo = wx.ComboBox(tab, choices=choices_trans, style=wx.CB_READONLY)
            combo.SetName(cat_trans)
            combo.SetSelection(0)
            for i, c in enumerate(choices):
                combo.SetClientData(i, c)
            hbox.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            hbox.Add(combo, 1, wx.EXPAND, 0)
            vbox.Add(hbox, 0, wx.EXPAND | wx.ALL, 5)
            self.design_combos.append(combo)
        self.btn_gen_design = wx.Button(tab, label=self._("gen_design"))
        self.btn_gen_design.Bind(wx.EVT_BUTTON, self.OnGenDesign)
        vbox.Add(self.btn_gen_design, 0, wx.EXPAND | wx.ALL, 5)
        tab.SetSizer(vbox)

    def SetupAdvTab(self, tab):
        vbox = wx.BoxSizer(wx.VERTICAL)
        lbl_steps = self._("steps")
        wx.StaticText(tab, label=lbl_steps)
        def_steps = self.cfg.get("ai_steps", 32) if self.cfg.get("remember_ai_settings", True) else 32
        self.spin_steps = wx.SpinCtrl(tab, value=str(def_steps), min=1, max=100)
        self.spin_steps.SetName(lbl_steps)
        vbox.Add(self.spin_steps, 0, wx.ALL, 5)
        
        lbl_cfg = self._("cfg")
        wx.StaticText(tab, label=lbl_cfg)
        def_cfg = self.cfg.get("ai_cfg", 2.0) if self.cfg.get("remember_ai_settings", True) else 2.0
        self.spin_cfg = wx.SpinCtrlDouble(tab, value=str(def_cfg), min=0.1, max=10.0, inc=0.1)
        self.spin_cfg.SetName(lbl_cfg)
        self.spin_cfg.SetToolTip(lbl_cfg)
        for child in self.spin_cfg.GetChildren(): child.SetName(lbl_cfg)
        vbox.Add(self.spin_cfg, 0, wx.ALL, 5)
        
        lbl_speed = self._("speed")
        wx.StaticText(tab, label=lbl_speed)
        def_speed = self.cfg.get("ai_speed", 1.0) if self.cfg.get("remember_ai_settings", True) else 1.0
        self.spin_speed = wx.SpinCtrlDouble(tab, value=str(def_speed), min=0.1, max=5.0, inc=0.1)
        self.spin_speed.SetName(lbl_speed)
        self.spin_speed.SetToolTip(lbl_speed)
        for child in self.spin_speed.GetChildren(): child.SetName(lbl_speed)
        vbox.Add(self.spin_speed, 0, wx.ALL, 5)
        
        lbl_denoise = self._("denoise")
        self.chk_denoise = wx.CheckBox(tab, label=lbl_denoise)
        self.chk_denoise.SetName(lbl_denoise)
        def_denoise = self.cfg.get("ai_denoise", True) if self.cfg.get("remember_ai_settings", True) else True
        self.chk_denoise.SetValue(def_denoise)
        vbox.Add(self.chk_denoise, 0, wx.ALL, 5)
        
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
        
        tab.SetSizer(vbox)
        
    def BrowseFor(self, txt_ctrl):
        with wx.FileDialog(self, self._("browse"), wildcard="Audio files (*.wav;*.mp3)|*.wav;*.mp3", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fd:
            if fd.ShowModal() != wx.ID_CANCEL:
                txt_ctrl.SetValue(fd.GetPath())

    def OnBrowseRefAudio(self, event):
        self.BrowseFor(self.clone_ref_audio)
        
    def RefreshPresets(self):
        self.combo_presets.Clear()
        self.combo_presets.Append(self._("no_preset"), None)
        
        if os.path.exists(PRESETS_DIR):
            pts = [f for f in os.listdir(PRESETS_DIR) if f.endswith(".pt")]
            display_mode = self.cfg.get("preset_display_mode", "name")
            
            for pt in pts:
                name_only = pt.replace(".pt", "")
                full_path = os.path.abspath(os.path.join(PRESETS_DIR, pt))
                
                if display_mode == "name":
                    disp = name_only
                elif display_mode == "path":
                    disp = full_path
                else: # name_path
                    disp = f"{name_only} ({full_path})"
                    
                self.combo_presets.Append(disp, pt)
                
        self.combo_presets.SetSelection(0)
        
    def Log(self, msg, success=False):
        self.status_text.AppendText(msg + "\n")
        if success and self.cfg.get("confirm_success", False):
            wx.CallAfter(lambda: wx.MessageBox(msg, self._("success_title"), wx.OK | wx.ICON_INFORMATION))

    def AutoLoadModel(self):
        if not self.model:
            self.OnToggleModel(None)

    def OnToggleModel(self, event):
        if self.model is None:
            def on_success():
                if self.model:
                    self.btn_toggle_model.SetLabel(self._("unload_model"))
                    self.Log("Model OK.", success=True)
                    self.clone_text.SetFocus()
                    wx.Bell()
            self.RunOperation("op_load_title", "op_load_msg", self._LoadModelWorker, success_callback=on_success)
        else:
            def on_success():
                self.model = None
                if torch and torch.cuda.is_available():
                    torch.cuda.empty_cache()
                self.btn_toggle_model.SetLabel(self._("load_model"))
                self.Log("Model zwolniony z pamiÄ™ci RAM / Model unloaded from RAM.", success=True)
                wx.Bell()
            self.RunOperation("op_unload_title", "op_unload_msg", self._UnloadModelWorker, success_callback=on_success)

    def _LoadModelWorker(self, op_dialog):
        try:
            device = get_best_device()
            if op_dialog.cancel_flag: return
            
            asr_name = self.cfg.get("asr_model_name", "")
            kwargs = {"device_map": device, "dtype": torch.float16, "load_asr": True}
            if asr_name: kwargs["asr_model_name"] = asr_name
            self.model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", **kwargs)

            if op_dialog.cancel_flag: 
                self.model = None
        except Exception as e:
            wx.CallAfter(self.Log, self._("msg_error") + str(e))
            
    def _UnloadModelWorker(self, op_dialog):
        import time
        for i in range(10): 
            if op_dialog.cancel_flag: return
            time.sleep(0.05)

    def GetGenConfig(self):
        return OmniVoiceGenerationConfig(
            num_step=self.spin_steps.GetValue(),
            guidance_scale=self.spin_cfg.GetValue(),
            denoise=self.chk_denoise.GetValue()
        )

    def OnGenClone(self, event):
        if not self.model:
            wx.MessageBox(self._("msg_load_first"), self._("error_title"))
            return
            
        text = self.clone_text.GetValue().strip()
        lang = self.clone_lang.GetValue()
        if lang == "Auto": lang = None
        
        ref_text = self.clone_ref_text.GetValue().strip() or None
        ref_audio = self.clone_ref_audio.GetValue().strip()
        preset_idx = self.combo_presets.GetSelection()
        preset = self.combo_presets.GetClientData(preset_idx) if preset_idx != wx.NOT_FOUND else None
        speed = self.spin_speed.GetValue()
        duration = self.spin_duration.GetValue() if self.chk_duration.GetValue() else None
        norm_txt = self.cfg.get("normalize_text", False)
        
        if not text:
            return
            
        use_preset = preset is not None
        if not use_preset and not os.path.exists(ref_audio):
            wx.MessageBox(self._("err_no_audio_preset"), self._("error_title"), wx.OK | wx.ICON_ERROR)
            return
            
        preset_path = os.path.join(PRESETS_DIR, preset) if use_preset else None
            
        def on_success():
            self.Log(self._("ready"), success=True)
            if self.audio_data is not None:
                self.btn_play.Enable()
                self.btn_save.Enable()
                self.btn_play.SetFocus()
                wx.Bell()
        
        self.RunOperation("op_gen_title", "op_gen_msg", self._GenCloneWorker, text, ref_audio, preset_path, ref_text, lang, speed, duration, norm_txt, success_callback=on_success)
        
    def _GenCloneWorker(self, op_dialog, text, ref_audio, preset_path, ref_text, lang, speed, duration, norm_txt):
        try:
            gen_config = self.GetGenConfig()
            if preset_path:
                prompt = VoiceClonePrompt.load(preset_path)
            else:
                prompt = self.model.create_voice_clone_prompt(ref_audio=ref_audio, ref_text=ref_text)
                
            if op_dialog.cancel_flag: return
            kwargs = {"text": text, "generation_config": gen_config, "voice_clone_prompt": prompt, "normalize_text": norm_txt}
            if lang: kwargs["language"] = lang
            if duration: kwargs["duration"] = duration
            else: kwargs["speed"] = speed
            audio = self.model.generate(**kwargs)
            if op_dialog.cancel_flag: return
            
            self.audio_data = audio[0]
        except Exception as e:
            if not op_dialog.cancel_flag:
                wx.CallAfter(self.Log, self._("msg_error") + str(e))


    def SetupAutoTab(self, tab):
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        wx.StaticText(tab, label=self._("auto_text_lbl"))
        self.auto_text = wx.TextCtrl(tab, style=wx.TE_MULTILINE)
        vbox.Add(self.auto_text, 1, wx.EXPAND | wx.ALL, 5)
        
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        wx.StaticText(tab, label=self._("auto_lang_lbl"))
        self.auto_lang = wx.ComboBox(tab, choices=_ALL_LANGUAGES, style=wx.CB_READONLY)
        self.auto_lang.SetSelection(0)
        hbox.Add(self.auto_lang, 0, wx.RIGHT, 10)
        
        self.btn_gen_auto = wx.Button(tab, label=self._("btn_gen_auto"))
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
                
        self.RunOperation(self._("op_auto_title"), self._("op_auto_msg"), self._GenAutoWorker, text, lang, speed, duration, norm_txt, success_callback=on_success)

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

    def OnGenDesign(self, event):
        if not self.model: return
        text = self.design_text.GetValue().strip()
        lang = self.design_lang.GetValue()
        if lang == "Auto": lang = None
        speed = self.spin_speed.GetValue()
        duration = self.spin_duration.GetValue() if self.chk_duration.GetValue() else None
        norm_txt = self.cfg.get("normalize_text", False)
        if not text: return
            
        instructs = []
        for c in self.design_combos:
            idx = c.GetSelection()
            if idx != wx.NOT_FOUND:
                eng_val = c.GetClientData(idx)
                if eng_val != "None":
                    instructs.append(eng_val)
                
        instruct = ", ".join(instructs) if instructs else None
        
        def on_success():
            if self.audio_data is not None:
                self.Log(self._("ready"), success=True)
                self.btn_play.Enable()
                self.btn_save.Enable()
                self.btn_play.SetFocus()
                wx.Bell()
                
        self.RunOperation("op_gen_title", "op_gen_msg", self._GenDesignWorker, text, lang, instruct, speed, duration, norm_txt, success_callback=on_success)

    def _GenDesignWorker(self, op_dialog, text, lang, instruct, speed, duration, norm_txt):
        try:
            gen_config = self.GetGenConfig()
            if op_dialog.cancel_flag: return
            kwargs = {"text": text, "instruct": instruct, "generation_config": gen_config, "normalize_text": norm_txt}
            if lang: kwargs["language"] = lang
            if duration: kwargs["duration"] = duration
            else: kwargs["speed"] = speed
            audio = self.model.generate(**kwargs)
            if op_dialog.cancel_flag: return
            
            self.audio_data = audio[0]
        except Exception as e:
            if not op_dialog.cancel_flag:
                wx.CallAfter(self.Log, self._("msg_error") + str(e))
            
    def OnSavePresetPrompt(self, event):
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
            SaveBasicConfig(self.cfg)
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
            event.Skip()

    def OnPlayAudio(self, event):
        if self.btn_play.GetLabel() in [self._("play"), self._("resume_play")]:
            if self.audio_data is not None and sd:
                if not hasattr(self, 'is_paused') or not self.is_paused:
                    self.current_frame = 0
                    self.total_frames = len(self.audio_data)
                    self.is_paused = False
                    
                frames_left = self.total_frames - self.current_frame
                sd.play(self.audio_data[self.current_frame:], samplerate=self.sample_rate)
                
                self.btn_play.SetLabel(self._("stop_play"))
                self.btn_pause.Enable()
                self.btn_pause.SetLabel(self._("btn_pause"))
                
                duration_ms = int((frames_left / self.sample_rate) * 1000)
                if hasattr(self, 'play_timer'): self.play_timer.Stop()
                
                def on_finish():
                    self.btn_play.SetLabel(self._("play"))
                    self.btn_pause.Disable()
                    self.is_paused = False
                    self.current_frame = 0
                    
                self.play_timer = wx.CallLater(duration_ms + 100, on_finish)
                
        else: # stop play
            if sd: sd.stop()
            if hasattr(self, 'play_timer'): self.play_timer.Stop()
            self.btn_play.SetLabel(self._("play"))
            self.btn_pause.Disable()
            self.btn_pause.SetLabel(self._("btn_pause"))
            self.is_paused = False
            self.current_frame = 0

    def OnPauseAudio(self, event):
        if not hasattr(self, 'is_paused'):
            self.is_paused = False
            
        if sd and self.btn_play.GetLabel() == self._("stop_play"):
            if not self.is_paused:
                self.is_paused = True
                if hasattr(self, 'play_timer'):
                    # Save progress
                    elapsed_ms = self.play_timer.GetInterval() - self.play_timer.TimeRemaining()
                    self.current_frame += int((elapsed_ms / 1000) * self.sample_rate)
                    self.play_timer.Stop()
                sd.stop()
                self.btn_play.SetLabel(self._("resume_play"))
                self.btn_pause.SetLabel(self._("play")) # Swap button text conceptually or just keep it "pause", actually disable it is better, no let's just make Play button "Resume"
                self.btn_pause.Disable()
                

    def OnSaveAudio(self, event):
        if self.audio_data is not None and sf:
            with wx.FileDialog(self, self._("save"), wildcard="WAV (*.wav)|*.wav", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fd:
                if fd.ShowModal() != wx.ID_CANCEL:
                    sf.write(fd.GetPath(), self.audio_data, self.sample_rate)
                    wx.MessageBox(self._("msg_save_ok"), self._("title_save"), wx.OK | wx.ICON_INFORMATION)

    def TogglePlayFile(self, btn, path_ctrl):
        if btn.GetLabel() == self._("play_ref"):
            path = path_ctrl.GetValue().strip()
            if not os.path.exists(path):
                wx.MessageBox(self._("err_file_not_found"), self._("error_title"), wx.OK | wx.ICON_ERROR)
                return
            try:
                data, fs = sf.read(path)
                sd.play(data, samplerate=fs)
                btn.SetLabel(self._("stop_play"))
                duration_ms = int((len(data) / fs) * 1000)
                timer = wx.CallLater(duration_ms + 100, lambda: btn.SetLabel(self._("play_ref")))
                setattr(self, f"timer_{id(btn)}", timer)
            except Exception as e:
                wx.MessageBox(self._("err_playback").format(e=str(e)), self._("error_title"), wx.OK | wx.ICON_ERROR)
        else:
            if sd: sd.stop()
            timer = getattr(self, f"timer_{id(btn)}", None)
            if timer: timer.Stop()
            btn.SetLabel(self._("play_ref"))

    def ToggleRecord(self, btn, path_ctrl):
        if btn.GetLabel() == self._("rec_ref"):
            btn.SetLabel(self._("stop_rec"))
            self.rec_data = []
            self.rec_fs = 24000
            
            def callback(indata, frames, time, status):
                self.rec_data.append(indata.copy())
                
            self.rec_stream = sd.InputStream(samplerate=self.rec_fs, channels=1, callback=callback)
            self.rec_stream.start()
        else:
            btn.SetLabel(self._("rec_ref"))
            if hasattr(self, 'rec_stream'):
                self.rec_stream.stop()
                self.rec_stream.close()
                
            if hasattr(self, 'rec_data') and self.rec_data:
                import numpy as np
                audio = np.concatenate(self.rec_data, axis=0)
                path = os.path.abspath("recorded_ref.wav")
                sf.write(path, audio, self.rec_fs)
                path_ctrl.SetValue(path)
                wx.Bell()



    def OnShowTags(self, event):
        wx.MessageBox(self._("msg_tags"), self._("title_tags"), wx.OK | wx.ICON_INFORMATION)

def main():
    app = wx.App(False)
    
    cfg = LoadBasicConfig()
    
    if not cfg.get("first_run_done", False):
        dlg = SettingsDialog(None, is_first_run=True, current_cfg=cfg)
        if dlg.ShowModal() == wx.ID_OK:
            cfg = dlg.cfg
            SaveBasicConfig(cfg)
        else:
            sys.exit(0)
    
    if not cfg.get("show_console") or cfg.get("force_splash"):
        splash = StartupSplash(None, cfg)
        if splash.ShowModal() != wx.ID_OK:
            sys.exit(0)
    else:
        global torch, np, sf, sd, OmniVoice, OmniVoiceGenerationConfig, VoiceClonePrompt, get_best_device, _ALL_LANGUAGES
        try:
            import soundfile as sf
            import sounddevice as sd
            import numpy as np
            import torch
            from omnivoice import OmniVoice, OmniVoiceGenerationConfig, VoiceClonePrompt
            from omnivoice.utils.common import get_best_device
            from omnivoice.utils.lang_map import LANG_NAMES, lang_display_name
            _ALL_LANGUAGES.clear()
            _ALL_LANGUAGES.extend(["Auto"] + sorted(lang_display_name(n) for n in LANG_NAMES))
        except ImportError:
            pass
            
    frame = OmniVoiceFrame(cfg, None)
    frame.Show(True)
    app.MainLoop()

if __name__ == '__main__':
    main()
