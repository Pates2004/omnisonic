import ctypes
import logging
import os
import threading

import wx
import wx.lib.scrolledpanel as scrolled

from .config import (
    CONFIG_FILE,
    DEFAULT_CONFIG,
    PRESETS_DIR,
    RECORDED_AUDIO_FILE,
    default_audio_directory,
    ensure_user_directories,
    load_config,
    locale_search_directories,
    migrate_legacy_user_data,
    save_config,
)
from .i18n import load_locales, translate
from .operations import OperationState, execute_worker
from .shortcuts import (
    SHORTCUT_DEFINITIONS,
    default_shortcut_bindings,
    default_shortcut_enabled,
    find_shortcut_conflicts,
    normalize_shortcut,
    shortcut_parts,
)
from .validation import preset_filename, safe_child_path, validate_filename_component

torch = None
np = None
sf = None
sd = None
OmniVoice = None
OmniVoiceGenerationConfig = None
VoiceClonePrompt = None
get_best_device = None
load_waveform = None

_ALL_LANGUAGES = ["Auto"]

_AUDIO_FILE_WILDCARD = (
    "Audio files (*.wav;*.flac;*.ogg;*.oga;*.opus;*.mp3;*.aiff;*.aif;*.au;*.caf)|"
    "*.wav;*.flac;*.ogg;*.oga;*.opus;*.mp3;*.aiff;*.aif;*.au;*.caf|"
    "All files (*.*)|*.*"
)

_CATEGORIES = {
    "Gender": ["None", "Male", "Female"],
    "Age": ["None", "Child", "Teenager", "Young Adult", "Middle-aged", "Elderly"],
    "Pitch": [
        "None",
        "Very Low Pitch",
        "Low Pitch",
        "Moderate Pitch",
        "High Pitch",
        "Very High Pitch",
    ],
    "Style": ["None", "Whisper"],
    "Accent": [
        "None",
        "American Accent",
        "Australian Accent",
        "British Accent",
        "Chinese Accent",
        "Canadian Accent",
        "Indian Accent",
        "Korean Accent",
        "Portuguese Accent",
        "Russian Accent",
        "Japanese Accent",
    ],
    "Dialect": [
        "None",
        "Henan Dialect",
        "Shaanxi Dialect",
        "Sichuan Dialect",
        "Guizhou Dialect",
        "Yunnan Dialect",
        "Guilin Dialect",
        "Jinan Dialect",
        "Shijiazhuang Dialect",
        "Gansu Dialect",
        "Ningxia Dialect",
        "Qingdao Dialect",
        "Northeast Dialect",
    ],
}

_DIALECT_INSTRUCTS = {
    "Henan Dialect": "河南话",
    "Shaanxi Dialect": "陕西话",
    "Sichuan Dialect": "四川话",
    "Guizhou Dialect": "贵州话",
    "Yunnan Dialect": "云南话",
    "Guilin Dialect": "桂林话",
    "Jinan Dialect": "济南话",
    "Shijiazhuang Dialect": "石家庄话",
    "Gansu Dialect": "甘肃话",
    "Ningxia Dialect": "宁夏话",
    "Qingdao Dialect": "青岛话",
    "Northeast Dialect": "东北话",
}


def LoadLocales():
    return load_locales(locale_search_directories())


LOCALE = LoadLocales()


def LoadBasicConfig():
    cfg = load_config(CONFIG_FILE)
    if cfg["language"] not in LOCALE and LOCALE:
        cfg["language"] = list(LOCALE.keys())[0]
    return cfg


def SaveBasicConfig(cfg):
    save_config(cfg, CONFIG_FILE)


def SetConsoleVisible(visible):
    if not hasattr(ctypes, "windll"):
        return False
    window = ctypes.windll.kernel32.GetConsoleWindow()
    if not window:
        return False
    ctypes.windll.user32.ShowWindow(window, 5 if visible else 0)
    return True


_SHORTCUT_WX_KEYS = {
    "Space": wx.WXK_SPACE,
    "Enter": wx.WXK_RETURN,
    "Tab": wx.WXK_TAB,
    "Escape": wx.WXK_ESCAPE,
    "Backspace": wx.WXK_BACK,
    "Delete": wx.WXK_DELETE,
    "Insert": wx.WXK_INSERT,
    "Home": wx.WXK_HOME,
    "End": wx.WXK_END,
    "PageUp": wx.WXK_PAGEUP,
    "PageDown": wx.WXK_PAGEDOWN,
    "Up": wx.WXK_UP,
    "Down": wx.WXK_DOWN,
    "Left": wx.WXK_LEFT,
    "Right": wx.WXK_RIGHT,
}
_SHORTCUT_WX_KEYS_REVERSED = {value: key for key, value in _SHORTCUT_WX_KEYS.items()}


def _wx_accelerator(shortcut, command_id):
    modifiers, key = shortcut_parts(shortcut)
    flags = wx.ACCEL_NORMAL
    if "Ctrl" in modifiers:
        flags |= wx.ACCEL_CTRL
    if "Alt" in modifiers:
        flags |= wx.ACCEL_ALT
    if "Shift" in modifiers:
        flags |= wx.ACCEL_SHIFT

    if len(key) == 1:
        key_code = ord(key)
    elif key.startswith("F") and key[1:].isdigit():
        key_code = getattr(wx, f"WXK_F{int(key[1:])}")
    else:
        key_code = _SHORTCUT_WX_KEYS[key]
    return flags, key_code, command_id


def _shortcut_from_key_event(event):
    key_code = event.GetKeyCode()
    if event.ControlDown() and 1 <= key_code <= 26:
        key_code += ord("A") - 1

    if key_code in _SHORTCUT_WX_KEYS_REVERSED:
        key = _SHORTCUT_WX_KEYS_REVERSED[key_code]
    elif wx.WXK_F1 <= key_code <= wx.WXK_F24:
        key = f"F{key_code - wx.WXK_F1 + 1}"
    elif 0 <= key_code < 256 and chr(key_code).isascii() and chr(key_code).isalnum():
        key = chr(key_code).upper()
    else:
        raise ValueError("unsupported key")

    parts = []
    if event.ControlDown():
        parts.append("Ctrl")
    if event.AltDown():
        parts.append("Alt")
    if event.ShiftDown():
        parts.append("Shift")
    parts.append(key)
    return normalize_shortcut("+".join(parts))


def LoadRuntimeDependencies():
    global torch, np, sf, sd, OmniVoice, OmniVoiceGenerationConfig
    global VoiceClonePrompt, get_best_device, load_waveform, _ALL_LANGUAGES

    import numpy as _np
    import sounddevice as _sd
    import soundfile as _sf
    import torch as _torch
    from omnivoice import OmniVoice as _OV
    from omnivoice import OmniVoiceGenerationConfig as _OVC
    from omnivoice import VoiceClonePrompt as _VCP
    from omnivoice.utils.common import get_best_device as _gbd
    from omnivoice.utils.audio import load_waveform as _load_waveform
    from omnivoice.utils.lang_map import LANG_NAMES, lang_display_name

    np = _np
    sd = _sd
    sf = _sf
    torch = _torch
    OmniVoice = _OV
    OmniVoiceGenerationConfig = _OVC
    VoiceClonePrompt = _VCP
    get_best_device = _gbd
    load_waveform = _load_waveform
    _ALL_LANGUAGES[:] = ["Auto"] + sorted(lang_display_name(n) for n in LANG_NAMES)


class StartupSplash:
    def __init__(self, parent, cfg):
        self.cfg = cfg
        self.parent = parent
        self._ = lambda key: translate(LOCALE, cfg.get("language", "en"), key)
        self.finished = False
        self.cancel_requested = False
        self.error = None

    def _confirm_cancel(self, event=None):
        if isinstance(event, wx.CloseEvent):
            event.Veto()
        if self.cancel_requested:
            return
        dialog = wx.MessageDialog(
            self.dialog,
            self._("close_warn"),
            self._("warning_title"),
            wx.YES_NO | wx.ICON_QUESTION,
        )
        confirmed = dialog.ShowModal() == wx.ID_YES
        dialog.Destroy()
        if confirmed:
            self.cancel_requested = True
            if hasattr(self, "cancel_button"):
                self.cancel_button.Disable()
            if hasattr(self, "label"):
                self.label.SetLabel(self._("cancel_pending"))

    def ShowModal(self):
        title = self._("startup_title")
        message = self._("startup_msg") or self._("msg_wait")
        use_native = self.cfg.get("use_native_dialogs", False)

        if use_native:
            self.dialog = wx.ProgressDialog(
                title,
                message,
                maximum=100,
                parent=self.parent,
                style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_SMOOTH,
            )
            threading.Thread(target=self.DoHeavyImports, daemon=True).start()
            while not self.finished:
                value = self.dialog.GetValue()
                cont, _ = self.dialog.Update(value + 1 if value < 100 else 0)
                if not cont and not self.cancel_requested:
                    self._confirm_cancel()
                    if not self.cancel_requested:
                        self.dialog.Resume()
                    else:
                        self.dialog.Update(value, self._("cancel_pending"))
                wx.MilliSleep(50)
                wx.GetApp().Yield()
            self.dialog.Destroy()
            result = wx.ID_CANCEL if self.cancel_requested or self.error else wx.ID_OK
        else:
            self.dialog = wx.Dialog(self.parent, title=title, size=(440, 180))
            panel = wx.Panel(self.dialog)
            layout = wx.BoxSizer(wx.VERTICAL)
            self.label = wx.StaticText(panel, label=message)
            layout.Add(self.label, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 15)
            gauge = wx.Gauge(panel, range=100)
            layout.Add(gauge, 0, wx.ALL | wx.EXPAND, 10)
            self.cancel_button = wx.Button(panel, label=self._("btn_cancel"))
            self.cancel_button.Bind(wx.EVT_BUTTON, self._confirm_cancel)
            self.dialog.Bind(wx.EVT_CLOSE, self._confirm_cancel)
            layout.Add(self.cancel_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 5)
            panel.SetSizer(layout)
            self.dialog.Centre()

            timer = wx.Timer(self.dialog)
            self.dialog.Bind(
                wx.EVT_TIMER,
                lambda event: (
                    gauge.SetValue((gauge.GetValue() + 5) % 101)
                    if self.cfg.get("fake_progress_numbers", False)
                    else gauge.Pulse()
                ),
                timer,
            )
            timer.Start(100)
            threading.Thread(target=self.DoHeavyImports, daemon=True).start()
            result = self.dialog.ShowModal()
            timer.Stop()
            self.dialog.Destroy()

        if self.error:
            wx.MessageBox(
                self._("startup_error").format(error=str(self.error)),
                self._("error_title"),
                wx.OK | wx.ICON_ERROR,
            )
            return wx.ID_CANCEL
        return result

    def DoHeavyImports(self):
        try:
            LoadRuntimeDependencies()
        except Exception as exc:
            self.error = exc
            logging.exception("Could not load OmniSonic runtime dependencies")
        finally:
            self.finished = True
            if not self.cfg.get("use_native_dialogs", False):
                result = wx.ID_CANCEL if self.cancel_requested or self.error else wx.ID_OK
                wx.CallAfter(self.dialog.EndModal, result)


class OperationDialog:
    def __init__(self, parent, cfg, title_key, msg_key, worker_func, *args):
        self.parent = parent
        self.cfg = cfg
        self._ = lambda key: translate(LOCALE, cfg.get("language", "en"), key)
        self.title = self._(title_key)
        self.msg = self._(msg_key)
        self.worker_func = worker_func
        self.args = args
        self.state = OperationState(name=title_key)
        self.dialog = None

    def _run_worker(self):
        execute_worker(self.state, self.worker_func, *self.args)
        if not self.cfg.get("use_native_dialogs", False):
            wx.CallAfter(self._finish_custom_dialog)

    def _finish_custom_dialog(self):
        if self.dialog and self.dialog.IsModal():
            result = wx.ID_OK if self.state.succeeded else wx.ID_CANCEL
            self.dialog.EndModal(result)

    def _request_cancel(self):
        if self.state.cancel_flag:
            return
        self.state.request_cancel()
        if hasattr(self, "cancel_button"):
            self.cancel_button.Disable()
        if hasattr(self, "label"):
            self.label.SetLabel(self._("cancel_pending"))

    def _confirm_cancel(self, event=None):
        if isinstance(event, wx.CloseEvent):
            event.Veto()
        if self.state.cancel_flag:
            return
        dialog = wx.MessageDialog(
            self.dialog,
            self._("stop_confirm"),
            self._("warning_title"),
            wx.YES_NO | wx.ICON_QUESTION,
        )
        confirmed = dialog.ShowModal() == wx.ID_YES
        dialog.Destroy()
        if confirmed:
            self._request_cancel()

    def ShowModal(self):
        use_native = self.cfg.get("use_native_dialogs", False)

        if use_native:
            self.dialog = wx.ProgressDialog(
                self.title,
                self.msg or self._("msg_wait"),
                maximum=100,
                parent=self.parent,
                style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_SMOOTH,
            )
            threading.Thread(target=self._run_worker, daemon=True).start()
            while not self.state.finished:
                value = self.dialog.GetValue()
                cont, _ = self.dialog.Update(value + 1 if value < 100 else 0)
                if not cont and not self.state.cancel_flag:
                    self._confirm_cancel()
                    if not self.state.cancel_flag:
                        self.dialog.Resume()
                    else:
                        self.dialog.Update(value, self._("cancel_pending"))
                wx.MilliSleep(50)
                wx.GetApp().Yield()
            self.dialog.Destroy()
        else:
            self.dialog = wx.Dialog(self.parent, title=self.title, size=(440, 180))
            panel = wx.Panel(self.dialog)
            layout = wx.BoxSizer(wx.VERTICAL)
            self.label = wx.StaticText(panel, label=self.msg)
            layout.Add(self.label, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 15)
            gauge = wx.Gauge(panel, range=100)
            layout.Add(gauge, 0, wx.ALL | wx.EXPAND, 10)
            self.cancel_button = wx.Button(panel, label=self._("btn_cancel"))
            self.cancel_button.Bind(wx.EVT_BUTTON, self._confirm_cancel)
            self.dialog.Bind(wx.EVT_CLOSE, self._confirm_cancel)
            layout.Add(self.cancel_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 5)
            panel.SetSizer(layout)
            self.dialog.Centre()

            timer = wx.Timer(self.dialog)
            self.dialog.Bind(
                wx.EVT_TIMER,
                lambda event: (
                    gauge.SetValue((gauge.GetValue() + 5) % 101)
                    if self.cfg.get("fake_progress_numbers", False)
                    else gauge.Pulse()
                ),
                timer,
            )
            timer.Start(100)
            threading.Thread(target=self._run_worker, daemon=True).start()
            self.dialog.ShowModal()
            timer.Stop()
            self.dialog.Destroy()
        return self.state


class DownloadDialog(wx.Dialog):
    def __init__(self, parent, title, label, repo_id, lang_func):
        super().__init__(parent, title=title, size=(440, 180))
        self._ = lang_func
        self.repo_id = repo_id
        self.state = OperationState(name=f"download:{repo_id}")

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

        self.t = threading.Thread(target=self._run_download, daemon=True)
        self.t.start()

    @property
    def succeeded(self):
        return self.state.succeeded

    @property
    def error(self):
        return self.state.error

    def _run_download(self):
        execute_worker(self.state, self._dl_worker)

    def OnTimer(self, event):
        app = wx.GetApp()
        cfg = (
            app.GetTopWindow().cfg
            if app and app.GetTopWindow() and hasattr(app.GetTopWindow(), "cfg")
            else {}
        )
        if cfg.get("fake_progress_numbers", False):
            self.gauge.SetValue((self.gauge.GetValue() + 5) % 101)
        else:
            self.gauge.Pulse()
        if self.state.finished:
            self.timer.Stop()
            self.EndModal(wx.ID_OK if self.state.succeeded else wx.ID_CANCEL)

    def OnCancel(self, event):
        if isinstance(event, wx.CloseEvent):
            event.Veto()
        if self.state.cancel_flag:
            return
        msg = self._("cancel_dl_prompt")
        title = self._("cancel_title")
        if wx.MessageBox(msg, title, wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.state.request_cancel()
            self.btn_cancel.Disable()
            self.lbl.SetLabel(self._("cancel_pending"))

    def _dl_worker(self, state):
        from huggingface_hub import snapshot_download

        result = snapshot_download(repo_id=self.repo_id)
        state.check_cancelled()
        return result


def is_model_cached(repo_id):
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id=repo_id, local_files_only=True)
        return True
    except Exception:
        return False


class AccessibleFloatCtrl(wx.TextCtrl):
    def __init__(self, parent, value, min_val, max_val, inc):
        super(AccessibleFloatCtrl, self).__init__(
            parent, value=str(value), style=wx.TE_PROCESS_ENTER
        )
        self.min_val = min_val
        self.max_val = max_val
        self.inc = inc
        self.Bind(wx.EVT_KEY_DOWN, self.OnKeyDown)

    def OnKeyDown(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_UP:
            self.Increment(self.inc)
        elif keycode == wx.WXK_DOWN:
            self.Increment(-self.inc)
        else:
            event.Skip()

    def Increment(self, amount):
        try:
            val = float(super(AccessibleFloatCtrl, self).GetValue())
            val += amount
            if val < self.min_val:
                val = self.min_val
            if val > self.max_val:
                val = self.max_val
            self.SetValue(str(round(val, 2)))
        except ValueError:
            pass

    def GetValue(self):
        try:
            value = float(super(AccessibleFloatCtrl, self).GetValue())
            return max(self.min_val, min(self.max_val, value))
        except ValueError:
            return self.min_val


class ShortcutCaptureDialog(wx.Dialog):
    def __init__(self, parent, translate_func):
        super().__init__(parent, title=translate_func("shortcut_capture_title"), size=(500, 210))
        self._ = translate_func
        self.captured_shortcut = None

        panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)
        self.instructions = wx.StaticText(panel, label=self._("shortcut_capture_prompt"))
        self.instructions.SetName(self._("shortcut_capture_prompt"))
        layout.Add(self.instructions, 1, wx.ALL | wx.EXPAND, 15)

        cancel_button = wx.Button(panel, wx.ID_CANCEL, self._("btn_cancel"))
        layout.Add(cancel_button, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 10)
        panel.SetSizer(layout)

        self.Bind(wx.EVT_CHAR_HOOK, self.OnKey)
        self.CentreOnParent()

    def OnKey(self, event):
        if event.GetKeyCode() in (wx.WXK_CONTROL, wx.WXK_ALT, wx.WXK_SHIFT):
            return
        if (
            event.GetKeyCode() == wx.WXK_ESCAPE
            and not event.ControlDown()
            and not event.AltDown()
            and not event.ShiftDown()
        ):
            self.EndModal(wx.ID_CANCEL)
            return
        try:
            self.captured_shortcut = _shortcut_from_key_event(event)
        except ValueError:
            self.instructions.SetLabel(self._("shortcut_capture_invalid"))
            self.instructions.GetParent().Layout()
            return
        self.EndModal(wx.ID_OK)


class PresetEditDialog(wx.Dialog):
    def __init__(self, parent, translate_func, name, ref_text):
        super().__init__(parent, title=translate_func("preset_edit_title"), size=(620, 360))
        self._ = translate_func

        panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)

        name_label = wx.StaticText(panel, label=self._("preset_edit_name"))
        layout.Add(name_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.name_ctrl = wx.TextCtrl(panel, value=name)
        self.name_ctrl.SetName(self._("preset_edit_name"))
        layout.Add(self.name_ctrl, 0, wx.ALL | wx.EXPAND, 10)

        source_label = wx.StaticText(panel, label=self._("preset_edit_source"))
        layout.Add(source_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        source_row = wx.BoxSizer(wx.HORIZONTAL)
        self.source_ctrl = wx.TextCtrl(panel)
        self.source_ctrl.SetName(self._("preset_edit_source"))
        source_row.Add(self.source_ctrl, 1, wx.EXPAND | wx.RIGHT, 5)
        browse_button = wx.Button(panel, label=self._("browse"))
        browse_button.Bind(wx.EVT_BUTTON, self.OnBrowse)
        source_row.Add(browse_button, 0, wx.EXPAND)
        layout.Add(source_row, 0, wx.ALL | wx.EXPAND, 10)

        ref_text_label = wx.StaticText(panel, label=self._("preset_edit_ref_text"))
        layout.Add(ref_text_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        self.ref_text_ctrl = wx.TextCtrl(panel, value=ref_text, style=wx.TE_MULTILINE)
        self.ref_text_ctrl.SetName(self._("preset_edit_ref_text"))
        layout.Add(self.ref_text_ctrl, 1, wx.ALL | wx.EXPAND, 10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(panel, wx.ID_OK, self._("btn_save"))
        cancel_button = wx.Button(panel, wx.ID_CANCEL, self._("btn_cancel"))
        buttons.Add(ok_button, 1, wx.RIGHT, 5)
        buttons.Add(cancel_button, 1)
        layout.Add(buttons, 0, wx.ALL | wx.EXPAND, 10)
        panel.SetSizer(layout)
        self.CentreOnParent()

    def OnBrowse(self, event):
        with wx.FileDialog(
            self,
            self._("browse"),
            wildcard=_AUDIO_FILE_WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.source_ctrl.SetValue(dialog.GetPath())


class SettingsDialog(wx.Dialog):
    def __init__(self, parent, is_first_run=False, current_cfg=None):
        self.cfg = current_cfg or LoadBasicConfig()
        self.is_first_run = is_first_run
        self.lang = self.cfg.get("language", "en")
        title = self._("first_run_title") if is_first_run else self._("settings_title")
        super(SettingsDialog, self).__init__(parent, title=title, size=(620, 680))

        self.InitUI()
        self.Centre()

    def _(self, key):
        return translate(LOCALE, self.lang, key)

    def InitUI(self):
        panel = wx.Panel(self)
        vbox_main = wx.BoxSizer(wx.VERTICAL)

        if self.is_first_run:
            lbl = wx.StaticText(panel, label=self._("first_run_msg"))
            vbox_main.Add(lbl, 0, wx.ALL | wx.EXPAND, 10)

        notebook = wx.Notebook(panel)
        tab_app = scrolled.ScrolledPanel(notebook)

        notebook.AddPage(tab_app, self._("tab_appearance"))
        if not self.is_first_run:
            tab_sys = scrolled.ScrolledPanel(notebook)
            tab_opts = scrolled.ScrolledPanel(notebook)
            tab_shortcuts = scrolled.ScrolledPanel(notebook)
            notebook.AddPage(tab_sys, self._("tab_system"))
            notebook.AddPage(tab_opts, self._("tab_ai_opts"))
            notebook.AddPage(tab_shortcuts, self._("tab_shortcuts"))

        vbox_app = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(tab_app, label=self._("lang_lbl"))
        vbox_app.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.avail_langs = list(LOCALE.keys())
        choices = [LOCALE[language].get("lang_name", language) for language in self.avail_langs]
        self.cb_lang = wx.ComboBox(tab_app, choices=choices, style=wx.CB_READONLY)
        self.cb_lang.SetName(self._("lang_lbl"))
        self.cb_lang.SetSelection(
            self.avail_langs.index(self.lang) if self.lang in self.avail_langs else 0
        )
        vbox_app.Add(self.cb_lang, 0, wx.ALL | wx.EXPAND, 5)

        label = wx.StaticText(tab_app, label=self._("theme_lbl"))
        vbox_app.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.cb_theme = wx.ComboBox(
            tab_app, choices=[self._("theme_light"), self._("theme_dark")], style=wx.CB_READONLY
        )
        self.cb_theme.SetName(self._("theme_lbl"))
        self.cb_theme.SetSelection(0 if self.cfg.get("theme", "light") == "light" else 1)
        vbox_app.Add(self.cb_theme, 0, wx.ALL | wx.EXPAND, 5)

        label = wx.StaticText(tab_app, label=self._("font_size_lbl"))
        vbox_app.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.spin_font = wx.SpinCtrl(
            tab_app, value=str(self.cfg.get("font_size", 10)), min=8, max=24
        )
        self.spin_font.SetName(self._("font_size_lbl"))
        vbox_app.Add(self.spin_font, 0, wx.ALL | wx.EXPAND, 5)
        tab_app.SetSizer(vbox_app)
        tab_app.SetupScrolling(scroll_x=False)

        if not self.is_first_run:
            vbox_sys = wx.BoxSizer(wx.VERTICAL)

            self.chk_hide_console = wx.CheckBox(tab_sys, label=self._("console_lbl"))
            self.chk_hide_console.SetName(self._("console_lbl"))
            self.chk_hide_console.SetValue(self.cfg.get("hide_console", True))
            vbox_sys.Add(self.chk_hide_console, 0, wx.ALL | wx.EXPAND, 5)

            label = wx.StaticText(tab_sys, label=self._("preset_disp_lbl"))
            vbox_sys.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
            self.cb_preset_disp = wx.ComboBox(
                tab_sys,
                choices=[self._("disp_name"), self._("disp_path"), self._("disp_both")],
                style=wx.CB_READONLY,
            )
            self.cb_preset_disp.SetName(self._("preset_disp_lbl"))
            cur_disp = self.cfg.get("preset_display_mode", "name")
            if cur_disp == "name":
                self.cb_preset_disp.SetSelection(0)
            elif cur_disp == "path":
                self.cb_preset_disp.SetSelection(1)
            else:
                self.cb_preset_disp.SetSelection(2)
            vbox_sys.Add(self.cb_preset_disp, 0, wx.ALL | wx.EXPAND, 5)

            label = wx.StaticText(tab_sys, label=self._("asr_model_lbl"))
            vbox_sys.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
            self.cb_asr = wx.ComboBox(
                tab_sys,
                choices=[
                    "openai/whisper-large-v3-turbo",
                    "openai/whisper-large-v3",
                    "openai/whisper-medium",
                    "openai/whisper-small",
                    "openai/whisper-base",
                    "openai/whisper-tiny",
                ],
                style=wx.CB_READONLY,
            )
            self.cb_asr.SetName(self._("asr_model_lbl"))
            cur_asr = self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo")
            if cur_asr in self.cb_asr.GetStrings():
                self.cb_asr.SetValue(cur_asr)
            else:
                self.cb_asr.SetValue("openai/whisper-large-v3-turbo")
            vbox_sys.Add(self.cb_asr, 0, wx.ALL | wx.EXPAND, 5)

            self.chk_preload_asr = wx.CheckBox(tab_sys, label=self._("preload_asr_lbl"))
            self.chk_preload_asr.SetName(self._("preload_asr_lbl"))
            self.chk_preload_asr.SetValue(self.cfg.get("preload_asr", False))
            vbox_sys.Add(self.chk_preload_asr, 0, wx.ALL | wx.EXPAND, 5)

            self.chk_clean_temp = wx.CheckBox(tab_sys, label=self._("clean_temp_lbl"))
            self.chk_clean_temp.SetName(self._("clean_temp_lbl"))
            self.chk_clean_temp.SetValue(self.cfg.get("clean_temp", True))
            vbox_sys.Add(self.chk_clean_temp, 0, wx.ALL | wx.EXPAND, 5)

            self.btn_clean_temp = wx.Button(tab_sys, label=self._("clean_temp_btn"))
            self.btn_clean_temp.Bind(wx.EVT_BUTTON, self.OnCleanTemp)
            vbox_sys.Add(self.btn_clean_temp, 0, wx.ALL | wx.EXPAND, 5)
            tab_sys.SetSizer(vbox_sys)
            tab_sys.SetupScrolling(scroll_x=False)

            vbox_opts = wx.BoxSizer(wx.VERTICAL)

            self.chk_force_splash = wx.CheckBox(tab_opts, label=self._("force_splash_lbl"))
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
            vbox_opts.Add(self.chk_remember_ai, 0, wx.ALL | wx.EXPAND, 5)

            self.chk_normalize_text = wx.CheckBox(tab_opts, label=self._("norm_text_lbl"))
            self.chk_normalize_text.SetName(self._("norm_text_lbl"))
            self.chk_normalize_text.SetValue(self.cfg.get("normalize_text", False))
            vbox_opts.Add(self.chk_normalize_text, 0, wx.ALL | wx.EXPAND, 5)

            # Autosave Generated
            self.chk_auto_gen = wx.CheckBox(tab_opts, label=self._("auto_save_gen"))
            self.chk_auto_gen.SetName(self._("auto_save_gen"))
            self.chk_auto_gen.SetValue(self.cfg.get("auto_save_gen", False))
            vbox_opts.Add(self.chk_auto_gen, 0, wx.ALL | wx.EXPAND, 5)

            self.chk_auto_gen_folder = wx.CheckBox(tab_opts, label=self._("auto_save_gen_folder"))
            self.chk_auto_gen_folder.SetName(self._("auto_save_gen_folder"))
            self.chk_auto_gen_folder.SetValue(self.cfg.get("auto_save_gen_folder", False))
            vbox_opts.Add(self.chk_auto_gen_folder, 0, wx.ALL | wx.EXPAND, 5)

            hbox_pref_gen = wx.BoxSizer(wx.HORIZONTAL)
            lbl_pref_gen = wx.StaticText(tab_opts, label=self._("prefix_gen"))
            self.txt_pref_gen = wx.TextCtrl(tab_opts, value=self.cfg.get("prefix_gen", "generated"))
            self.txt_pref_gen.SetName(self._("prefix_gen"))
            hbox_pref_gen.Add(lbl_pref_gen, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            hbox_pref_gen.Add(self.txt_pref_gen, 1, wx.EXPAND)
            vbox_opts.Add(hbox_pref_gen, 0, wx.ALL | wx.EXPAND, 5)

            # Autosave Recorded
            self.chk_auto_rec = wx.CheckBox(tab_opts, label=self._("auto_save_rec"))
            self.chk_auto_rec.SetName(self._("auto_save_rec"))
            self.chk_auto_rec.SetValue(self.cfg.get("auto_save_rec", False))
            vbox_opts.Add(self.chk_auto_rec, 0, wx.ALL | wx.EXPAND, 5)

            self.chk_auto_rec_folder = wx.CheckBox(tab_opts, label=self._("auto_save_rec_folder"))
            self.chk_auto_rec_folder.SetName(self._("auto_save_rec_folder"))
            self.chk_auto_rec_folder.SetValue(self.cfg.get("auto_save_rec_folder", False))
            vbox_opts.Add(self.chk_auto_rec_folder, 0, wx.ALL | wx.EXPAND, 5)

            hbox_pref_rec = wx.BoxSizer(wx.HORIZONTAL)
            lbl_pref_rec = wx.StaticText(tab_opts, label=self._("prefix_rec"))
            self.txt_pref_rec = wx.TextCtrl(tab_opts, value=self.cfg.get("prefix_rec", "record"))
            self.txt_pref_rec.SetName(self._("prefix_rec"))
            hbox_pref_rec.Add(lbl_pref_rec, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            hbox_pref_rec.Add(self.txt_pref_rec, 1, wx.EXPAND)
            vbox_opts.Add(hbox_pref_rec, 0, wx.ALL | wx.EXPAND, 5)

            hbox_reset = wx.BoxSizer(wx.HORIZONTAL)

            self.btn_reset_ai = wx.Button(tab_opts, label=self._("reset_ai_btn"))
            self.btn_reset_app = wx.Button(tab_opts, label=self._("reset_app_btn"))

            self.btn_reset_ai.Bind(wx.EVT_BUTTON, self.OnResetAI)
            self.btn_reset_app.Bind(wx.EVT_BUTTON, self.OnResetApp)

            hbox_reset.Add(self.btn_reset_ai, 1, wx.EXPAND | wx.RIGHT, 5)
            hbox_reset.Add(self.btn_reset_app, 1, wx.EXPAND, 0)
            vbox_opts.Add(hbox_reset, 0, wx.ALL | wx.EXPAND, 5)
            tab_opts.SetSizer(vbox_opts)
            tab_opts.SetupScrolling(scroll_x=False)
            self.SetupShortcutsTab(tab_shortcuts)

        vbox_main.Add(notebook, 1, wx.EXPAND | wx.ALL, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        btn_ok = wx.Button(panel, label=self._("btn_save"))
        btn_cancel = wx.Button(panel, label=self._("btn_cancel"))

        btn_ok.Bind(wx.EVT_BUTTON, self.OnSave)
        btn_cancel.Bind(wx.EVT_BUTTON, self.OnCancel)

        hbox.Add(btn_ok, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox.Add(btn_cancel, 1, wx.EXPAND, 0)

        vbox_main.Add(hbox, 0, wx.ALL | wx.EXPAND, 5)

        panel.SetSizer(vbox_main)
        self.Bind(wx.EVT_CLOSE, self.OnClose)

    def SetupShortcutsTab(self, tab):
        self.shortcut_bindings = dict(
            self.cfg.get("shortcut_bindings", default_shortcut_bindings())
        )
        self.shortcut_enabled = dict(self.cfg.get("shortcut_enabled", default_shortcut_enabled()))
        self._updating_shortcut_editor = False

        layout = wx.BoxSizer(wx.VERTICAL)
        self.chk_shortcuts_enabled = wx.CheckBox(tab, label=self._("shortcuts_global_enabled"))
        self.chk_shortcuts_enabled.SetName(self._("shortcuts_global_enabled"))
        self.chk_shortcuts_enabled.SetValue(self.cfg.get("shortcuts_enabled", True))
        layout.Add(self.chk_shortcuts_enabled, 0, wx.ALL | wx.EXPAND, 5)

        list_label = wx.StaticText(tab, label=self._("shortcuts_list_label"))
        layout.Add(list_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.list_shortcuts = wx.ListBox(tab, choices=[])
        self.list_shortcuts.SetName(self._("shortcuts_list_label"))
        for index in range(len(SHORTCUT_DEFINITIONS)):
            self.list_shortcuts.Append(self._shortcut_list_text(index))
        self.list_shortcuts.Bind(wx.EVT_LISTBOX, self.OnShortcutSelected)
        layout.Add(self.list_shortcuts, 1, wx.ALL | wx.EXPAND, 5)

        self.chk_shortcut_enabled = wx.CheckBox(tab, label=self._("shortcut_item_enabled"))
        self.chk_shortcut_enabled.SetName(self._("shortcut_item_enabled"))
        self.chk_shortcut_enabled.Bind(wx.EVT_CHECKBOX, self.OnShortcutEnabledChanged)
        layout.Add(self.chk_shortcut_enabled, 0, wx.ALL | wx.EXPAND, 5)

        editor_label = wx.StaticText(tab, label=self._("shortcut_value_label"))
        layout.Add(editor_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        editor_row = wx.BoxSizer(wx.HORIZONTAL)
        self.txt_shortcut = wx.TextCtrl(tab)
        self.txt_shortcut.SetName(self._("shortcut_value_label"))
        self.txt_shortcut.Bind(wx.EVT_TEXT, self.OnShortcutTextChanged)
        editor_row.Add(self.txt_shortcut, 1, wx.EXPAND | wx.RIGHT, 5)

        capture_button = wx.Button(tab, label=self._("shortcut_capture_button"))
        capture_button.Bind(wx.EVT_BUTTON, self.OnCaptureShortcut)
        editor_row.Add(capture_button, 0, wx.EXPAND | wx.RIGHT, 5)

        restore_button = wx.Button(tab, label=self._("shortcuts_restore_defaults"))
        restore_button.Bind(wx.EVT_BUTTON, self.OnRestoreShortcutDefaults)
        editor_row.Add(restore_button, 0, wx.EXPAND)
        layout.Add(editor_row, 0, wx.ALL | wx.EXPAND, 5)

        help_text = wx.StaticText(tab, label=self._("shortcut_format_help"))
        help_text.Wrap(560)
        layout.Add(help_text, 0, wx.ALL | wx.EXPAND, 5)

        tab.SetSizer(layout)
        tab.SetupScrolling(scroll_x=False)
        self.list_shortcuts.SetSelection(0)
        self._load_selected_shortcut()

    def _shortcut_list_text(self, index):
        definition = SHORTCUT_DEFINITIONS[index]
        binding = self.shortcut_bindings.get(definition.key, definition.default)
        state_key = (
            "shortcut_state_enabled"
            if self.shortcut_enabled.get(definition.key, True)
            else "shortcut_state_disabled"
        )
        return f"{self._(definition.label_key)}: {binding} — {self._(state_key)}"

    def _selected_shortcut(self):
        index = self.list_shortcuts.GetSelection()
        if index == wx.NOT_FOUND:
            return None, None
        return index, SHORTCUT_DEFINITIONS[index]

    def _refresh_shortcut_list_item(self, index):
        selection = self.list_shortcuts.GetSelection()
        self.list_shortcuts.SetString(index, self._shortcut_list_text(index))
        self.list_shortcuts.SetSelection(selection)

    def _load_selected_shortcut(self):
        _index, definition = self._selected_shortcut()
        if definition is None:
            return
        self._updating_shortcut_editor = True
        self.txt_shortcut.SetValue(self.shortcut_bindings.get(definition.key, definition.default))
        self.chk_shortcut_enabled.SetValue(self.shortcut_enabled.get(definition.key, True))
        self._updating_shortcut_editor = False

    def OnShortcutSelected(self, event):
        self._load_selected_shortcut()

    def OnShortcutTextChanged(self, event):
        if self._updating_shortcut_editor:
            return
        index, definition = self._selected_shortcut()
        if definition is None:
            return
        self.shortcut_bindings[definition.key] = self.txt_shortcut.GetValue().strip()
        self._refresh_shortcut_list_item(index)

    def OnShortcutEnabledChanged(self, event):
        if self._updating_shortcut_editor:
            return
        index, definition = self._selected_shortcut()
        if definition is None:
            return
        self.shortcut_enabled[definition.key] = self.chk_shortcut_enabled.GetValue()
        self._refresh_shortcut_list_item(index)

    def OnCaptureShortcut(self, event):
        dialog = ShortcutCaptureDialog(self, self._)
        if dialog.ShowModal() == wx.ID_OK and dialog.captured_shortcut:
            self.txt_shortcut.SetValue(dialog.captured_shortcut)
            self.txt_shortcut.SetFocus()
        dialog.Destroy()

    def _restore_shortcut_defaults(self):
        self.shortcut_bindings = default_shortcut_bindings()
        self.shortcut_enabled = default_shortcut_enabled()
        self.chk_shortcuts_enabled.SetValue(True)
        for index in range(len(SHORTCUT_DEFINITIONS)):
            self._refresh_shortcut_list_item(index)
        self._load_selected_shortcut()

    def OnRestoreShortcutDefaults(self, event):
        self._restore_shortcut_defaults()

    def _save_shortcut_settings(self):
        normalized_bindings = {}
        for definition in SHORTCUT_DEFINITIONS:
            try:
                normalized_bindings[definition.key] = normalize_shortcut(
                    self.shortcut_bindings.get(definition.key, definition.default)
                )
            except ValueError:
                wx.MessageBox(
                    self._("shortcut_invalid").format(name=self._(definition.label_key)),
                    self._("error_title"),
                    wx.OK | wx.ICON_ERROR,
                )
                return False

        conflicts = find_shortcut_conflicts(normalized_bindings, self.shortcut_enabled)
        if conflicts:
            first, second, shortcut = conflicts[0]
            definitions = {definition.key: definition for definition in SHORTCUT_DEFINITIONS}
            wx.MessageBox(
                self._("shortcut_conflict").format(
                    first=self._(definitions[first].label_key),
                    second=self._(definitions[second].label_key),
                    shortcut=shortcut,
                ),
                self._("error_title"),
                wx.OK | wx.ICON_ERROR,
            )
            return False

        self.shortcut_bindings = normalized_bindings
        self.cfg["shortcuts_enabled"] = self.chk_shortcuts_enabled.GetValue()
        self.cfg["shortcut_bindings"] = dict(normalized_bindings)
        self.cfg["shortcut_enabled"] = {
            definition.key: self.shortcut_enabled.get(definition.key, True)
            for definition in SHORTCUT_DEFINITIONS
        }
        return True

    def OnResetAI(self, event):
        if (
            wx.MessageBox(
                self._("reset_ai_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_WARNING
            )
            == wx.YES
        ):
            self.cfg["ai_steps"] = 32
            self.cfg["ai_cfg"] = 2.0
            self.cfg["ai_speed"] = 1.0
            self.cfg["ai_denoise"] = True
            self.cfg["ai_t_shift"] = 0.1
            self.cfg["ai_layer_penalty_factor"] = 5.0
            self.cfg["ai_position_temperature"] = 5.0
            self.cfg["ai_class_temperature"] = 0.0
            self.cfg["ai_preprocess_prompt"] = True
            self.cfg["ai_postprocess_output"] = True
            self.cfg["ai_audio_chunk_duration"] = 15.0
            self.cfg["ai_audio_chunk_threshold"] = 30.0
            self.cfg["ai_pad_duration"] = 0.1
            self.cfg["ai_fade_duration"] = 0.1
            self.cfg["clone_instruct"] = ""
            self.cfg["design_instruct"] = ""
            self.cfg["use_duration"] = False
            self.cfg["duration_val"] = 5.0
            parent = self.GetParent()
            if hasattr(parent, "spin_steps"):
                parent.spin_steps.SetValue(32)
                parent.spin_cfg.SetValue("2.0")
                parent.spin_speed.SetValue("1.0")
                parent.chk_denoise.SetValue(True)
                parent.spin_t_shift.SetValue("0.1")
                parent.spin_layer_penalty.SetValue("5.0")
                parent.spin_position_temperature.SetValue("5.0")
                parent.spin_class_temperature.SetValue("0.0")
                parent.chk_preprocess_prompt.SetValue(True)
                parent.chk_postprocess_output.SetValue(True)
                parent.spin_chunk_duration.SetValue("15.0")
                parent.spin_chunk_threshold.SetValue("30.0")
                parent.spin_pad_duration.SetValue("0.1")
                parent.spin_fade_duration.SetValue("0.1")
                parent.clone_instruct.Clear()
                parent.design_custom_instruct.Clear()
                if hasattr(parent, "chk_duration"):
                    parent.chk_duration.SetValue(False)
                    parent.spin_duration.SetValue(5.0)
            wx.MessageBox(self._("reset_ok"), self._("info_title"), wx.OK | wx.ICON_INFORMATION)

    def OnResetApp(self, event):
        if (
            wx.MessageBox(
                self._("reset_app_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_WARNING
            )
            == wx.YES
        ):
            defaults = DEFAULT_CONFIG
            default_language = defaults["language"]
            self.cb_lang.SetSelection(
                self.avail_langs.index(default_language)
                if default_language in self.avail_langs
                else 0
            )
            self.cb_theme.SetSelection(0 if defaults["theme"] == "light" else 1)
            self.spin_font.SetValue(defaults["font_size"])
            self.chk_hide_console.SetValue(defaults["hide_console"])
            self.cb_preset_disp.SetSelection(0)
            self.cb_asr.SetValue(defaults["asr_model_name"])
            self.chk_preload_asr.SetValue(defaults["preload_asr"])
            self.chk_force_splash.SetValue(defaults["force_splash"])
            self.chk_show_progress.SetValue(defaults["show_progress"])
            self.chk_fake_progress.SetValue(defaults["fake_progress_numbers"])
            self.chk_use_native.SetValue(defaults["use_native_dialogs"])
            self.chk_warn_exit.SetValue(defaults["warn_exit"])
            self.chk_confirm_success.SetValue(defaults["confirm_success"])
            self.chk_remember_ai.SetValue(defaults["remember_ai_settings"])
            self.chk_normalize_text.SetValue(defaults["normalize_text"])
            self.chk_clean_temp.SetValue(defaults["clean_temp"])
            self.chk_auto_gen.SetValue(defaults["auto_save_gen"])
            self.chk_auto_gen_folder.SetValue(defaults["auto_save_gen_folder"])
            self.txt_pref_gen.SetValue(defaults["prefix_gen"])
            self.chk_auto_rec.SetValue(defaults["auto_save_rec"])
            self.chk_auto_rec_folder.SetValue(defaults["auto_save_rec_folder"])
            self.txt_pref_rec.SetValue(defaults["prefix_rec"])
            self.cfg.update(defaults)
            self._restore_shortcut_defaults()

            parent = self.GetParent()
            if hasattr(parent, "spin_steps"):
                parent.spin_steps.SetValue(defaults["ai_steps"])
                parent.spin_cfg.SetValue(str(defaults["ai_cfg"]))
                parent.spin_speed.SetValue(str(defaults["ai_speed"]))
                parent.chk_denoise.SetValue(defaults["ai_denoise"])
                parent.spin_t_shift.SetValue(str(defaults["ai_t_shift"]))
                parent.spin_layer_penalty.SetValue(str(defaults["ai_layer_penalty_factor"]))
                parent.spin_position_temperature.SetValue(str(defaults["ai_position_temperature"]))
                parent.spin_class_temperature.SetValue(str(defaults["ai_class_temperature"]))
                parent.chk_preprocess_prompt.SetValue(defaults["ai_preprocess_prompt"])
                parent.chk_postprocess_output.SetValue(defaults["ai_postprocess_output"])
                parent.spin_chunk_duration.SetValue(str(defaults["ai_audio_chunk_duration"]))
                parent.spin_chunk_threshold.SetValue(str(defaults["ai_audio_chunk_threshold"]))
                parent.spin_pad_duration.SetValue(str(defaults["ai_pad_duration"]))
                parent.spin_fade_duration.SetValue(str(defaults["ai_fade_duration"]))
                parent.clone_instruct.SetValue(defaults["clone_instruct"])
                parent.design_custom_instruct.SetValue(defaults["design_instruct"])
                parent.chk_duration.SetValue(defaults["use_duration"])
                parent.spin_duration.SetValue(defaults["duration_val"])
            wx.MessageBox(self._("reset_ok"), self._("info_title"), wx.OK | wx.ICON_INFORMATION)

    def OnCleanTemp(self, event):
        temp_files = [RECORDED_AUDIO_FILE]
        count = 0
        freed_bytes = 0

        for path in temp_files:
            if os.path.exists(path):
                try:
                    freed_bytes += os.path.getsize(path)
                    os.remove(path)
                    count += 1
                except OSError as exc:
                    logging.warning("Could not remove temporary file %s: %s", path, exc)

        if count > 0:
            freed_mb = freed_bytes / (1024 * 1024)
            msg = (
                self._("clean_stats")
                .replace("{count}", str(count))
                .replace("{mb}", str(round(freed_mb, 2)))
            )
            wx.MessageBox(msg, self._("success_title"), wx.OK | wx.ICON_INFORMATION)
        else:
            wx.MessageBox(
                self._("clean_none"), self._("success_title"), wx.OK | wx.ICON_INFORMATION
            )

    def OnSave(self, event):
        self.lang = self.avail_langs[self.cb_lang.GetSelection()]
        self.cfg["language"] = self.lang
        self.cfg["theme"] = "light" if self.cb_theme.GetSelection() == 0 else "dark"
        self.cfg["font_size"] = self.spin_font.GetValue()

        if not self.is_first_run:
            try:
                prefix_gen = validate_filename_component(
                    self.txt_pref_gen.GetValue(), label=self._("prefix_gen")
                )
                prefix_rec = validate_filename_component(
                    self.txt_pref_rec.GetValue(), label=self._("prefix_rec")
                )
            except ValueError as exc:
                wx.MessageBox(
                    self._("invalid_filename").format(error=str(exc)),
                    self._("error_title"),
                    wx.OK | wx.ICON_ERROR,
                )
                return

            if not self._save_shortcut_settings():
                return

            new_asr = self.cb_asr.GetValue()
            if new_asr != self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo"):
                if not is_model_cached(new_asr):
                    msg = self._("dl_model_prompt").replace("{name}", new_asr)
                    title = self._("dl_title")
                    if wx.MessageBox(msg, title, wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                        dlg = DownloadDialog(
                            self,
                            title,
                            self._("download_model_status").format(name=new_asr),
                            new_asr,
                            self._,
                        )
                        dlg.ShowModal()
                        if dlg.succeeded:
                            self.cfg["asr_model_name"] = new_asr
                        else:
                            if dlg.error:
                                wx.MessageBox(
                                    self._("download_failed").format(error=str(dlg.error)),
                                    self._("error_title"),
                                    wx.OK | wx.ICON_ERROR,
                                )
                            self.cb_asr.SetValue(
                                self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo")
                            )
                            dlg.Destroy()
                            return
                        dlg.Destroy()
                    else:
                        self.cb_asr.SetValue(
                            self.cfg.get("asr_model_name", "openai/whisper-large-v3-turbo")
                        )
                        return
                else:
                    self.cfg["asr_model_name"] = new_asr

            self.cfg["hide_console"] = self.chk_hide_console.GetValue()
            idx = self.cb_preset_disp.GetSelection()
            self.cfg["preset_display_mode"] = (
                "name" if idx == 0 else ("path" if idx == 1 else "name_path")
            )
            self.cfg["force_splash"] = self.chk_force_splash.GetValue()
            self.cfg["show_progress"] = self.chk_show_progress.GetValue()
            self.cfg["fake_progress_numbers"] = self.chk_fake_progress.GetValue()
            self.cfg["use_native_dialogs"] = self.chk_use_native.GetValue()
            self.cfg["warn_exit"] = self.chk_warn_exit.GetValue()
            self.cfg["confirm_success"] = self.chk_confirm_success.GetValue()
            self.cfg["remember_ai_settings"] = self.chk_remember_ai.GetValue()
            self.cfg["normalize_text"] = self.chk_normalize_text.GetValue()
            self.cfg["clean_temp"] = self.chk_clean_temp.GetValue()
            self.cfg["preload_asr"] = self.chk_preload_asr.GetValue()
            self.cfg["auto_save_gen"] = self.chk_auto_gen.GetValue()
            self.cfg["auto_save_gen_folder"] = self.chk_auto_gen_folder.GetValue()
            self.cfg["prefix_gen"] = prefix_gen
            self.cfg["auto_save_rec"] = self.chk_auto_rec.GetValue()
            self.cfg["auto_save_rec_folder"] = self.chk_auto_rec_folder.GetValue()
            self.cfg["prefix_rec"] = prefix_rec
            if hasattr(self.GetParent(), "chk_duration"):
                self.cfg["use_duration"] = self.GetParent().chk_duration.GetValue()
                self.cfg["duration_val"] = self.GetParent().spin_duration.GetValue()

        self.cfg["first_run_done"] = True
        if self.is_first_run:
            wx.MessageBox(
                self._("first_run_success"), self._("info_title"), wx.OK | wx.ICON_INFORMATION
            )
        self.EndModal(wx.ID_OK)

    def OnCancel(self, event):
        self.HandleCancel(event)

    def OnClose(self, event):
        self.HandleCancel(event)

    def HandleCancel(self, event=None):
        dlg = wx.MessageDialog(
            self, self._("exit_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION
        )
        confirmed = dlg.ShowModal() == wx.ID_YES
        dlg.Destroy()
        if confirmed:
            self.EndModal(wx.ID_CANCEL)
        elif isinstance(event, wx.CloseEvent):
            event.Veto()


class OmniVoiceFrame(wx.Frame):
    def __init__(self, cfg, *args, **kw):
        super(OmniVoiceFrame, self).__init__(*args, **kw)

        self.cfg = cfg
        self.model = None
        self.audio_data = None
        self.sample_rate = 24000
        self.current_op = None

        ensure_user_directories()
        self.ApplyConsoleState()

        self.InitUI()
        self.ApplyTheme()
        self.ApplyFontSize()
        self.SetSize((960, 850))
        self.SetMinSize((720, 620))
        self.Centre()

        self.Bind(wx.EVT_CLOSE, self.OnCloseWindow)

        wx.CallLater(500, self.AutoLoadModel)

    def _(self, key):
        return translate(LOCALE, self.cfg.get("language", "en"), key)

    def ApplyConsoleState(self):
        SetConsoleVisible(not self.cfg.get("hide_console", True))

    def ApplyTheme(self):
        theme = self.cfg.get("theme", "light")
        bg_color = wx.Colour(40, 40, 40) if theme == "dark" else wx.NullColour
        fg_color = wx.Colour(220, 220, 220) if theme == "dark" else wx.NullColour

        self.SetBackgroundColour(bg_color)
        self.SetForegroundColour(fg_color)

        def color_children(parent):
            for child in parent.GetChildren():
                if theme == "light" or not isinstance(
                    child,
                    (wx.TextCtrl, wx.ComboBox, wx.SpinCtrl, wx.SpinCtrlDouble, wx.Button, wx.Gauge),
                ):
                    child.SetBackgroundColour(bg_color)
                    child.SetForegroundColour(fg_color)
                color_children(child)

        color_children(self)
        self.Layout()
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

    def ApplyShortcutSettings(self):
        bindings = self.cfg.get("shortcut_bindings", default_shortcut_bindings())
        enabled = self.cfg.get("shortcut_enabled", default_shortcut_enabled())
        globally_enabled = self.cfg.get("shortcuts_enabled", True)
        conflicting_actions = {
            second for _first, second, _shortcut in find_shortcut_conflicts(bindings, enabled)
        }
        accelerator_entries = []

        for definition in SHORTCUT_DEFINITIONS:
            item, menu_label_key = self.shortcut_menu_items[definition.key]
            try:
                shortcut = normalize_shortcut(bindings.get(definition.key, definition.default))
            except ValueError:
                shortcut = definition.default
            shortcut_active = (
                globally_enabled
                and enabled.get(definition.key, True)
                and definition.key not in conflicting_actions
            )
            shortcut_label = (
                shortcut
                if shortcut_active
                else self._("shortcut_menu_disabled").format(shortcut=shortcut)
            )
            item.SetItemLabel(f"{self._(menu_label_key)} ({shortcut_label})")
            if shortcut_active:
                accelerator_entries.append(_wx_accelerator(shortcut, item.GetId()))

        self.SetAcceleratorTable(wx.AcceleratorTable(accelerator_entries))

    def InitUI(self):
        self.SetTitle(self._("title"))

        menubar = wx.MenuBar()
        progMenu = wx.Menu()

        self.item_open_reference = progMenu.Append(wx.ID_OPEN, self._("menu_open_reference"))
        self.Bind(wx.EVT_MENU, self.OnShortcutOpen, self.item_open_reference)

        self.item_generate = progMenu.Append(wx.ID_ANY, self._("menu_generate"))
        self.Bind(wx.EVT_MENU, self.OnShortcutGenerate, self.item_generate)

        self.item_save_result = progMenu.Append(wx.ID_SAVE, self._("menu_save_result"))
        self.Bind(wx.EVT_MENU, self.OnShortcutSave, self.item_save_result)
        self.item_save_result.Enable(False)

        self.item_save_preset = progMenu.Append(wx.ID_ANY, self._("btn_save_preset_clone"))
        self.Bind(wx.EVT_MENU, self.OnShortcutSavePreset, self.item_save_preset)

        self.item_record = progMenu.Append(wx.ID_ANY, self._("menu_record"))
        self.Bind(wx.EVT_MENU, self.OnShortcutRecord, self.item_record)

        self.item_play_pause = progMenu.Append(wx.ID_ANY, self._("menu_play_pause"))
        self.Bind(wx.EVT_MENU, self.OnShortcutPlayPause, self.item_play_pause)
        self.item_play_pause.Enable(False)

        self.item_stop_playback = progMenu.Append(wx.ID_ANY, self._("stop_play"))
        self.Bind(wx.EVT_MENU, self.OnShortcutStopPlayback, self.item_stop_playback)

        self.shortcut_menu_items = {
            "open_reference": (self.item_open_reference, "menu_open_reference"),
            "generate": (self.item_generate, "menu_generate"),
            "save_result": (self.item_save_result, "menu_save_result"),
            "save_preset": (self.item_save_preset, "btn_save_preset_clone"),
            "record": (self.item_record, "menu_record"),
            "play_pause": (self.item_play_pause, "menu_play_pause"),
            "stop_playback": (self.item_stop_playback, "stop_play"),
        }

        progMenu.AppendSeparator()
        self.item_settings = progMenu.Append(wx.ID_ANY, self._("menu_settings"))
        self.Bind(wx.EVT_MENU, self.OnOpenSettings, self.item_settings)

        item_exit = progMenu.Append(wx.ID_EXIT, self._("menu_exit"))
        self.Bind(wx.EVT_MENU, lambda e: self.Close(), item_exit)

        menubar.Append(progMenu, self._("menu_prog"))

        helpMenu = wx.Menu()
        item_tags = helpMenu.Append(wx.ID_ANY, self._("menu_help_tags"))
        self.Bind(wx.EVT_MENU, self.OnShowTags, item_tags)
        menubar.Append(helpMenu, self._("menu_help"))

        self.SetMenuBar(menubar)
        self.ApplyShortcutSettings()

        self.panel = wx.Panel(self)
        self.main_vbox = wx.BoxSizer(wx.VERTICAL)

        hbox_top = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_toggle_model = wx.Button(self.panel, label=self._("load_model"))
        self.btn_toggle_model.Bind(wx.EVT_BUTTON, self.OnToggleModel)

        hbox_top.Add(self.btn_toggle_model, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        self.main_vbox.Add(hbox_top, 0, wx.EXPAND)

        self.notebook = wx.Notebook(self.panel)
        self.tab_clone = wx.Panel(self.notebook)
        self.tab_presets = wx.Panel(self.notebook)
        self.tab_design = wx.Panel(self.notebook)
        self.tab_adv = scrolled.ScrolledPanel(self.notebook)

        self.tab_auto = wx.Panel(self.notebook)

        self.notebook.AddPage(self.tab_clone, self._("tab_clone"))
        self.notebook.AddPage(self.tab_presets, self._("tab_presets"))
        self.notebook.AddPage(self.tab_design, self._("tab_design"))
        self.notebook.AddPage(self.tab_auto, self._("tab_auto"))
        self.notebook.AddPage(self.tab_adv, self._("tab_adv"))

        self.SetupCloneTab(self.tab_clone)
        self.SetupPresetsTab(self.tab_presets)
        self.SetupDesignTab(self.tab_design)
        self.SetupAutoTab(self.tab_auto)
        self.SetupAdvTab(self.tab_adv)

        self.main_vbox.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)

        status_label = wx.StaticText(self.panel, label=self._("status"))
        self.main_vbox.Add(status_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.status_text = wx.TextCtrl(
            self.panel, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(-1, 80)
        )
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

        self.btn_stop_audio = wx.Button(self.panel, label=self._("stop_play"))
        self.btn_stop_audio.Bind(wx.EVT_BUTTON, self.OnStopAudio)
        self.btn_stop_audio.Hide()

        self.btn_save = wx.Button(self.panel, label=self._("save"))
        self.btn_save.Bind(wx.EVT_BUTTON, self.OnSaveAudio)
        self.btn_save.Disable()

        hbox_audio.Add(self.btn_play, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_audio.Add(self.btn_stop_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_audio.Add(self.btn_save, 1, wx.EXPAND, 0)
        self.main_vbox.Add(hbox_audio, 0, wx.EXPAND | wx.ALL, 5)

        self.panel.SetSizer(self.main_vbox)
        self.RefreshPresets()

    def OnProgTimer(self, event):
        if self.cfg.get("fake_progress_numbers", False):
            self.gauge.SetValue((self.gauge.GetValue() + 2) % 101)
        else:
            self.gauge.Pulse()

    def OnShortcutOpen(self, event):
        self.notebook.SetSelection(0)
        self.OnBrowseRefAudio(event)

    def OnShortcutGenerate(self, event):
        page = self.notebook.GetCurrentPage()
        actions = (
            (self.tab_clone, self.btn_gen_clone, self.OnGenClone),
            (self.tab_design, self.btn_gen_design, self.OnGenDesign),
            (self.tab_auto, self.btn_gen_auto, self.OnGenAuto),
        )
        for target_page, button, handler in actions:
            if page is target_page:
                if button.IsEnabled():
                    handler(event)
                else:
                    wx.Bell()
                return
        wx.Bell()

    def OnShortcutSave(self, event):
        if self.audio_data is None:
            wx.Bell()
            return
        self.OnSaveAudio(event)

    def OnShortcutSavePreset(self, event):
        self.notebook.SetSelection(0)
        if self.btn_save_preset.IsEnabled():
            self.OnSavePresetPrompt(event)
        else:
            wx.Bell()

    def OnShortcutRecord(self, event):
        self.notebook.SetSelection(0)
        self.ToggleRecord(self.btn_rec_ref, self.clone_ref_audio)

    def OnShortcutPlayPause(self, event):
        if self.btn_play.IsEnabled():
            self.OnPlayAudio(event)
        else:
            wx.Bell()

    def OnShortcutStopPlayback(self, event):
        self.OnStopAudio(event)

    def OnStopOperation(self, event):
        if self.current_op and not self.current_op.finished:
            dlg = wx.MessageDialog(
                self, self._("stop_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION
            )
            confirmed = dlg.ShowModal() == wx.ID_YES
            dlg.Destroy()
            if confirmed:
                self.current_op.request_cancel()
                self.btn_stop.Disable()
                self.Log(self._("cancel_pending"))

    def _set_operation_controls_enabled(self, enabled):
        for name in (
            "btn_gen_clone",
            "btn_gen_design",
            "btn_gen_auto",
            "btn_save_preset",
            "btn_transcribe_ref",
            "list_presets",
            "btn_toggle_model",
        ):
            control = getattr(self, name, None)
            if control:
                control.Enable(enabled)
        has_presets = bool(
            enabled and hasattr(self, "list_presets") and self.list_presets.GetCount()
        )
        for name in (
            "btn_edit_preset",
            "btn_del_preset_manager",
            "btn_del_all_presets_manager",
        ):
            control = getattr(self, name, None)
            if control:
                control.Enable(has_presets)
        if hasattr(self, "item_settings"):
            self.item_settings.Enable(enabled)
        if hasattr(self, "item_generate"):
            self.item_generate.Enable(enabled)
        if hasattr(self, "item_save_preset"):
            self.item_save_preset.Enable(enabled)

    def _complete_operation(self, state, success_callback):
        if state.error is not None:
            message = self._("msg_error") + str(state.error)
            self.Log(message)
            wx.MessageBox(message, self._("error_title"), wx.OK | wx.ICON_ERROR)
        elif state.cancel_flag:
            self.Log(self._("operation_cancelled"))
        elif success_callback:
            try:
                success_callback(state.result)
            except Exception as exc:
                logging.exception("Operation success callback failed")
                message = self._("msg_error") + str(exc)
                self.Log(message)
                wx.MessageBox(message, self._("error_title"), wx.OK | wx.ICON_ERROR)

    def RunOperation(self, title_key, msg_key, worker_func, *args, success_callback=None):
        if self.current_op and not self.current_op.finished:
            wx.MessageBox(
                self._("operation_busy"),
                self._("warning_title"),
                wx.OK | wx.ICON_WARNING,
            )
            return None

        if self.cfg.get("show_progress", True):
            dlg = OperationDialog(self, self.cfg, title_key, msg_key, worker_func, *args)
            self.current_op = dlg.state
            self._set_operation_controls_enabled(False)
            state = dlg.ShowModal()
            self.current_op = None
            self._set_operation_controls_enabled(True)
            self._complete_operation(state, success_callback)
            return state
        else:
            self.Log(self._(msg_key))
            state = OperationState(name=title_key)
            self.current_op = state
            self.btn_stop.Enable()
            self.gauge.SetValue(0)
            self.prog_timer.Start(50)

            self._set_operation_controls_enabled(False)

            def wrapper():
                execute_worker(state, worker_func, *args)
                wx.CallAfter(self.EndOperation, state, success_callback)

            threading.Thread(target=wrapper, daemon=True).start()
            return state

    def EndOperation(self, state, success_callback):
        self.prog_timer.Stop()
        self.gauge.SetValue(0)
        self.btn_stop.Disable()

        self._set_operation_controls_enabled(True)
        if self.current_op is state:
            self.current_op = None
        self._complete_operation(state, success_callback)

    def OnOpenSettings(self, event):
        dlg = SettingsDialog(self, is_first_run=False, current_cfg=self.cfg.copy())
        if dlg.ShowModal() == wx.ID_OK:
            old_lang = self.cfg["language"]
            old_asr = self.cfg.get("asr_model_name")
            old_preload = self.cfg.get("preload_asr", False)
            try:
                SaveBasicConfig(dlg.cfg)
            except OSError as exc:
                wx.MessageBox(
                    self._("config_save_failed").format(error=str(exc)),
                    self._("error_title"),
                    wx.OK | wx.ICON_ERROR,
                )
                dlg.Destroy()
                return
            self.cfg = dlg.cfg
            self.ApplyConsoleState()
            self.ApplyShortcutSettings()
            self.ApplyTheme()
            self.ApplyFontSize()
            if old_lang != self.cfg["language"]:
                wx.MessageBox(self._("restart_lang"), self._("info_title"))
            if self.model and old_asr != self.cfg.get("asr_model_name"):
                self.model._asr_model_name = self.cfg["asr_model_name"]
                self.model._asr_pipe = None
            if self.model and old_preload != self.cfg.get("preload_asr", False):
                wx.MessageBox(self._("model_reload_required"), self._("info_title"))
        dlg.Destroy()

    def OnCloseWindow(self, event):
        if self.current_op and not self.current_op.finished:
            dlg = wx.MessageDialog(
                self, self._("close_busy"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION
            )
            confirmed = dlg.ShowModal() == wx.ID_YES
            dlg.Destroy()
            if confirmed:
                self.current_op.request_cancel()
                self.Log(self._("cancel_pending"))
            event.Veto()
            return

        if self.cfg.get("warn_exit", True):
            dlg = wx.MessageDialog(
                self, self._("close_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION
            )
            confirmed = dlg.ShowModal() == wx.ID_YES
            dlg.Destroy()
            if not confirmed:
                event.Veto()
                return

        if self.cfg.get("remember_ai_settings", True):
            if hasattr(self, "spin_steps"):
                self.cfg["ai_steps"] = self.spin_steps.GetValue()
                self.cfg["ai_cfg"] = self.spin_cfg.GetValue()
                self.cfg["ai_speed"] = self.spin_speed.GetValue()
                self.cfg["ai_denoise"] = self.chk_denoise.GetValue()
                self.cfg["ai_t_shift"] = self.spin_t_shift.GetValue()
                self.cfg["ai_layer_penalty_factor"] = self.spin_layer_penalty.GetValue()
                self.cfg["ai_position_temperature"] = self.spin_position_temperature.GetValue()
                self.cfg["ai_class_temperature"] = self.spin_class_temperature.GetValue()
                self.cfg["ai_preprocess_prompt"] = self.chk_preprocess_prompt.GetValue()
                self.cfg["ai_postprocess_output"] = self.chk_postprocess_output.GetValue()
                self.cfg["ai_audio_chunk_duration"] = self.spin_chunk_duration.GetValue()
                self.cfg["ai_audio_chunk_threshold"] = self.spin_chunk_threshold.GetValue()
                self.cfg["ai_pad_duration"] = self.spin_pad_duration.GetValue()
                self.cfg["ai_fade_duration"] = self.spin_fade_duration.GetValue()
                self.cfg["use_duration"] = self.chk_duration.GetValue()
                self.cfg["duration_val"] = self.spin_duration.GetValue()
                self.cfg["clone_lang"] = self.clone_lang.GetValue()
                self.cfg["clone_instruct"] = self.clone_instruct.GetValue()
                self.cfg["design_lang"] = self.design_lang.GetValue()
                self.cfg["design_instruct"] = self.design_custom_instruct.GetValue()
                self.cfg["auto_lang"] = self.auto_lang.GetValue()
        try:
            SaveBasicConfig(self.cfg)
        except OSError as exc:
            wx.MessageBox(
                self._("config_save_failed").format(error=str(exc)),
                self._("error_title"),
                wx.OK | wx.ICON_ERROR,
            )
            event.Veto()
            return

        if self.cfg.get("clean_temp", True):
            if os.path.exists(RECORDED_AUDIO_FILE):
                try:
                    os.remove(RECORDED_AUDIO_FILE)
                except OSError as exc:
                    logging.warning("Could not remove temporary recording: %s", exc)

        if hasattr(self, "rec_stream"):
            try:
                self.rec_stream.stop()
                self.rec_stream.close()
            except Exception as exc:
                logging.warning("Could not close recording stream: %s", exc)

        self.OnStopAudio(None)
        self.Destroy()

    def SetupCloneTab(self, tab):
        vbox = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(tab, label=self._("text_to_read"))
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.clone_text = wx.TextCtrl(tab, style=wx.TE_MULTILINE, size=(-1, 100))
        self.clone_text.SetName(self._("text_to_read"))
        vbox.Add(self.clone_text, 0, wx.EXPAND | wx.ALL, 5)
        label = wx.StaticText(tab, label=self._("preset_list"))
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        hbox_p = wx.BoxSizer(wx.HORIZONTAL)
        self.combo_presets = wx.ComboBox(tab, style=wx.CB_READONLY)

        btn_refresh = wx.Button(tab, label=self._("refresh"))
        btn_refresh.Bind(wx.EVT_BUTTON, lambda e: self.RefreshPresets())

        hbox_p.Add(self.combo_presets, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_p.Add(btn_refresh, 0, wx.EXPAND, 0)
        vbox.Add(hbox_p, 0, wx.EXPAND | wx.ALL, 5)
        label = wx.StaticText(tab, label=self._("ref_audio"))
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        hbox_ref = wx.BoxSizer(wx.HORIZONTAL)
        self.clone_ref_audio = wx.TextCtrl(tab)
        self.clone_ref_audio.SetName(self._("ref_audio"))
        btn_browse = wx.Button(tab, label=self._("browse"))
        btn_browse.Bind(wx.EVT_BUTTON, self.OnBrowseRefAudio)

        self.btn_play_ref = wx.Button(tab, label=self._("play_ref"))
        self.btn_play_ref.Bind(
            wx.EVT_BUTTON,
            lambda e: self.TogglePlayFile(
                self.btn_play_ref, self.clone_ref_audio, self.btn_stop_ref, tab
            ),
        )

        self.btn_stop_ref = wx.Button(tab, label=self._("stop_play"))
        self.btn_stop_ref.Bind(
            wx.EVT_BUTTON, lambda e: self.StopPlayFile(self.btn_play_ref, self.btn_stop_ref, tab)
        )
        self.btn_stop_ref.Hide()

        self.btn_rec_ref = wx.Button(tab, label=self._("rec_ref"))
        self.btn_rec_ref.Bind(
            wx.EVT_BUTTON, lambda e: self.ToggleRecord(self.btn_rec_ref, self.clone_ref_audio)
        )

        hbox_ref.Add(self.clone_ref_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(btn_browse, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_play_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_stop_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        hbox_ref.Add(self.btn_rec_ref, 0, wx.EXPAND | wx.RIGHT, 5)
        vbox.Add(hbox_ref, 0, wx.EXPAND | wx.ALL, 5)
        label = wx.StaticText(tab, label=self._("ref_text"))
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        ref_text_row = wx.BoxSizer(wx.HORIZONTAL)
        self.clone_ref_text = wx.TextCtrl(tab)
        self.clone_ref_text.SetName(self._("ref_text"))
        ref_text_row.Add(self.clone_ref_text, 1, wx.EXPAND | wx.RIGHT, 5)
        self.btn_transcribe_ref = wx.Button(tab, label=self._("transcribe_ref"))
        self.btn_transcribe_ref.Bind(wx.EVT_BUTTON, self.OnTranscribeReference)
        ref_text_row.Add(self.btn_transcribe_ref, 0, wx.EXPAND)
        vbox.Add(ref_text_row, 0, wx.EXPAND | wx.ALL, 5)

        instruct_label = wx.StaticText(tab, label=self._("clone_instruct"))
        vbox.Add(instruct_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.clone_instruct = wx.TextCtrl(tab)
        self.clone_instruct.SetName(self._("clone_instruct"))
        if self.cfg.get("remember_ai_settings", True):
            self.clone_instruct.SetValue(self.cfg.get("clone_instruct", ""))
        vbox.Add(self.clone_instruct, 0, wx.EXPAND | wx.ALL, 5)
        label = wx.StaticText(tab, label=self._("lang_select"))
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.clone_lang = wx.ComboBox(tab, choices=_ALL_LANGUAGES, style=wx.CB_READONLY)
        self.clone_lang.SetName(self._("lang_select"))
        def_clone_lang = (
            self.cfg.get("clone_lang", "Auto")
            if self.cfg.get("remember_ai_settings", True)
            else "Auto"
        )
        if def_clone_lang not in _ALL_LANGUAGES:
            def_clone_lang = "Auto"
        self.clone_lang.SetValue(def_clone_lang)
        vbox.Add(self.clone_lang, 0, wx.EXPAND | wx.ALL, 5)
        self.btn_gen_clone = wx.Button(tab, label=self._("gen_clone"))
        self.btn_gen_clone.Bind(wx.EVT_BUTTON, self.OnGenClone)
        vbox.Add(self.btn_gen_clone, 0, wx.EXPAND | wx.ALL, 5)
        tab.SetSizer(vbox)

    def SetupPresetsTab(self, tab):
        vbox = wx.BoxSizer(wx.VERTICAL)

        list_label = wx.StaticText(tab, label=self._("preset_manager_list"))
        vbox.Add(list_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.list_presets = wx.ListBox(tab)
        self.list_presets.SetName(self._("preset_manager_list"))
        self.list_presets.Bind(wx.EVT_KEY_DOWN, self.OnPresetManagerKeyDown)
        self.list_presets.Bind(wx.EVT_LISTBOX_DCLICK, self.OnEditPreset)
        vbox.Add(self.list_presets, 1, wx.ALL | wx.EXPAND, 5)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        refresh_button = wx.Button(tab, label=self._("refresh"))
        refresh_button.Bind(wx.EVT_BUTTON, lambda event: self.RefreshPresets())
        buttons.Add(refresh_button, 1, wx.RIGHT, 5)

        self.btn_edit_preset = wx.Button(tab, label=self._("btn_edit_preset"))
        self.btn_edit_preset.Bind(wx.EVT_BUTTON, self.OnEditPreset)
        buttons.Add(self.btn_edit_preset, 1, wx.RIGHT, 5)

        self.btn_del_preset_manager = wx.Button(tab, label=self._("btn_del_preset"))
        self.btn_del_preset_manager.Bind(wx.EVT_BUTTON, self.OnDelPreset)
        buttons.Add(self.btn_del_preset_manager, 1, wx.RIGHT, 5)

        self.btn_del_all_presets_manager = wx.Button(tab, label=self._("btn_del_all_presets"))
        self.btn_del_all_presets_manager.Bind(wx.EVT_BUTTON, self.OnDelAllPresets)
        buttons.Add(self.btn_del_all_presets_manager, 1)
        vbox.Add(buttons, 0, wx.ALL | wx.EXPAND, 5)

        source_label = wx.StaticText(tab, label=self._("preset_source_audio"))
        vbox.Add(source_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        source_row = wx.BoxSizer(wx.HORIZONTAL)
        self.preset_source_audio = wx.TextCtrl(tab)
        self.preset_source_audio.SetName(self._("preset_source_audio"))
        source_row.Add(self.preset_source_audio, 1, wx.EXPAND | wx.RIGHT, 5)
        browse_button = wx.Button(tab, label=self._("browse"))
        browse_button.Bind(wx.EVT_BUTTON, lambda event: self.BrowseFor(self.preset_source_audio))
        source_row.Add(browse_button, 0, wx.EXPAND)
        vbox.Add(source_row, 0, wx.ALL | wx.EXPAND, 5)

        ref_text_label = wx.StaticText(tab, label=self._("preset_source_ref_text"))
        vbox.Add(ref_text_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.preset_source_ref_text = wx.TextCtrl(tab)
        self.preset_source_ref_text.SetName(self._("preset_source_ref_text"))
        vbox.Add(self.preset_source_ref_text, 0, wx.ALL | wx.EXPAND, 5)

        self.btn_save_preset = wx.Button(tab, label=self._("btn_save_preset_clone"))
        self.btn_save_preset.Bind(wx.EVT_BUTTON, self.OnSaveManagedPreset)
        vbox.Add(self.btn_save_preset, 0, wx.ALL | wx.EXPAND, 5)

        tab.SetSizer(vbox)

    def SetupDesignTab(self, tab):
        vbox = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(tab, label=self._("text_to_read"))
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.design_text = wx.TextCtrl(tab, style=wx.TE_MULTILINE, size=(-1, 100))
        self.design_text.SetName(self._("text_to_read"))
        vbox.Add(self.design_text, 0, wx.EXPAND | wx.ALL, 5)
        label = wx.StaticText(tab, label=self._("lang_select"))
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.design_lang = wx.ComboBox(tab, choices=_ALL_LANGUAGES, style=wx.CB_READONLY)
        self.design_lang.SetName(self._("lang_select"))
        def_design_lang = (
            self.cfg.get("design_lang", "Auto")
            if self.cfg.get("remember_ai_settings", True)
            else "Auto"
        )
        if def_design_lang not in _ALL_LANGUAGES:
            def_design_lang = "Auto"
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
                combo.SetClientData(i, _DIALECT_INSTRUCTS.get(c, c))
            hbox.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
            hbox.Add(combo, 1, wx.EXPAND, 0)
            vbox.Add(hbox, 0, wx.EXPAND | wx.ALL, 5)
            self.design_combos.append(combo)
        custom_label = wx.StaticText(tab, label=self._("design_custom_instruct"))
        vbox.Add(custom_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.design_custom_instruct = wx.TextCtrl(tab)
        self.design_custom_instruct.SetName(self._("design_custom_instruct"))
        if self.cfg.get("remember_ai_settings", True):
            self.design_custom_instruct.SetValue(self.cfg.get("design_instruct", ""))
        vbox.Add(self.design_custom_instruct, 0, wx.ALL | wx.EXPAND, 5)
        self.btn_gen_design = wx.Button(tab, label=self._("gen_design"))
        self.btn_gen_design.Bind(wx.EVT_BUTTON, self.OnGenDesign)
        vbox.Add(self.btn_gen_design, 0, wx.EXPAND | wx.ALL, 5)
        tab.SetSizer(vbox)

    def SetupAdvTab(self, tab):
        vbox = wx.BoxSizer(wx.VERTICAL)
        lbl_steps = self._("steps")
        label = wx.StaticText(tab, label=lbl_steps)
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        def_steps = (
            self.cfg.get("ai_steps", 32) if self.cfg.get("remember_ai_settings", True) else 32
        )
        self.spin_steps = wx.SpinCtrl(tab, value=str(def_steps), min=1, max=100)
        self.spin_steps.SetName(lbl_steps)
        vbox.Add(self.spin_steps, 0, wx.ALL, 5)

        lbl_cfg = self._("cfg")
        label = wx.StaticText(tab, label=lbl_cfg)
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        def_cfg = self.cfg.get("ai_cfg", 2.0) if self.cfg.get("remember_ai_settings", True) else 2.0
        self.spin_cfg = AccessibleFloatCtrl(tab, value=def_cfg, min_val=0.1, max_val=10.0, inc=0.1)
        self.spin_cfg.SetName(lbl_cfg)
        self.spin_cfg.SetToolTip(lbl_cfg)

        vbox.Add(self.spin_cfg, 0, wx.ALL, 5)

        lbl_speed = self._("speed")
        label = wx.StaticText(tab, label=lbl_speed)
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        def_speed = (
            self.cfg.get("ai_speed", 1.0) if self.cfg.get("remember_ai_settings", True) else 1.0
        )
        self.spin_speed = AccessibleFloatCtrl(
            tab, value=def_speed, min_val=0.1, max_val=5.0, inc=0.1
        )
        self.spin_speed.SetName(lbl_speed)
        self.spin_speed.SetToolTip(lbl_speed)

        vbox.Add(self.spin_speed, 0, wx.ALL, 5)

        lbl_denoise = self._("denoise")
        self.chk_denoise = wx.CheckBox(tab, label=lbl_denoise)
        self.chk_denoise.SetName(lbl_denoise)
        def_denoise = (
            self.cfg.get("ai_denoise", True) if self.cfg.get("remember_ai_settings", True) else True
        )
        self.chk_denoise.SetValue(def_denoise)
        vbox.Add(self.chk_denoise, 0, wx.ALL, 5)

        remember = self.cfg.get("remember_ai_settings", True)

        def add_float_control(attribute, label_key, config_key, default, minimum, maximum, inc):
            text = self._(label_key)
            vbox.Add(wx.StaticText(tab, label=text), 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
            value = self.cfg.get(config_key, default) if remember else default
            control = AccessibleFloatCtrl(
                tab, value=value, min_val=minimum, max_val=maximum, inc=inc
            )
            control.SetName(text)
            control.SetToolTip(text)
            setattr(self, attribute, control)
            vbox.Add(control, 0, wx.ALL, 5)

        add_float_control("spin_t_shift", "t_shift", "ai_t_shift", 0.1, 0.001, 10.0, 0.01)
        add_float_control(
            "spin_layer_penalty",
            "layer_penalty_factor",
            "ai_layer_penalty_factor",
            5.0,
            0.0,
            100.0,
            0.1,
        )
        add_float_control(
            "spin_position_temperature",
            "position_temperature",
            "ai_position_temperature",
            5.0,
            0.0,
            100.0,
            0.1,
        )
        add_float_control(
            "spin_class_temperature",
            "class_temperature",
            "ai_class_temperature",
            0.0,
            0.0,
            100.0,
            0.1,
        )

        self.chk_preprocess_prompt = wx.CheckBox(tab, label=self._("preprocess_prompt"))
        self.chk_preprocess_prompt.SetName(self._("preprocess_prompt"))
        self.chk_preprocess_prompt.SetValue(
            self.cfg.get("ai_preprocess_prompt", True) if remember else True
        )
        vbox.Add(self.chk_preprocess_prompt, 0, wx.ALL, 5)

        self.chk_postprocess_output = wx.CheckBox(tab, label=self._("postprocess_output"))
        self.chk_postprocess_output.SetName(self._("postprocess_output"))
        self.chk_postprocess_output.SetValue(
            self.cfg.get("ai_postprocess_output", True) if remember else True
        )
        vbox.Add(self.chk_postprocess_output, 0, wx.ALL, 5)

        add_float_control(
            "spin_chunk_duration",
            "audio_chunk_duration",
            "ai_audio_chunk_duration",
            15.0,
            0.0,
            3600.0,
            1.0,
        )
        add_float_control(
            "spin_chunk_threshold",
            "audio_chunk_threshold",
            "ai_audio_chunk_threshold",
            30.0,
            0.0,
            3600.0,
            1.0,
        )
        add_float_control(
            "spin_pad_duration",
            "pad_duration",
            "ai_pad_duration",
            0.1,
            0.0,
            10.0,
            0.05,
        )
        add_float_control(
            "spin_fade_duration",
            "fade_duration",
            "ai_fade_duration",
            0.1,
            0.0,
            10.0,
            0.05,
        )

        lbl_dur = self._("duration_lbl")
        self.chk_duration = wx.CheckBox(tab, label=lbl_dur)
        self.chk_duration.SetName(lbl_dur)
        self.chk_duration.SetValue(self.cfg.get("use_duration", False))
        vbox.Add(self.chk_duration, 0, wx.ALL, 5)

        self.spin_duration = wx.SpinCtrlDouble(
            tab, value=str(self.cfg.get("duration_val", 5.0)), min=0.1, max=100.0, inc=0.5
        )
        self.spin_duration.SetName(lbl_dur)
        self.spin_duration.SetToolTip(lbl_dur)
        for child in self.spin_duration.GetChildren():
            child.SetName(lbl_dur)
        vbox.Add(self.spin_duration, 0, wx.ALL, 5)

        tab.SetSizer(vbox)
        tab.SetupScrolling(scroll_x=False)

    def BrowseFor(self, txt_ctrl):
        with wx.FileDialog(
            self,
            self._("browse"),
            wildcard=_AUDIO_FILE_WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as fd:
            if fd.ShowModal() != wx.ID_CANCEL:
                txt_ctrl.SetValue(fd.GetPath())

    def OnBrowseRefAudio(self, event):
        self.BrowseFor(self.clone_ref_audio)

    def OnTranscribeReference(self, event):
        if not self.model:
            wx.MessageBox(self._("msg_load_first"), self._("error_title"))
            return
        path = self.clone_ref_audio.GetValue().strip()
        if not os.path.isfile(path):
            wx.MessageBox(
                self._("err_file_not_found"), self._("error_title"), wx.OK | wx.ICON_ERROR
            )
            return

        def on_success(text):
            self.clone_ref_text.SetValue(text)
            self.Log(self._("transcribe_complete"), success=True)
            self.clone_ref_text.SetFocus()

        self.RunOperation(
            "op_transcribe_title",
            "op_transcribe_msg",
            self._TranscribeReferenceWorker,
            self.model,
            path,
            success_callback=on_success,
        )

    def _TranscribeReferenceWorker(self, state, model, path):
        state.check_cancelled()
        if getattr(model, "_asr_pipe", None) is None:
            model.load_asr_model()
        state.check_cancelled()
        waveform, sample_rate = load_waveform(path)
        text = model.transcribe((waveform, sample_rate))
        state.check_cancelled()
        return text

    def RefreshPresets(self):
        previous_managed = None
        if hasattr(self, "list_presets"):
            selection = self.list_presets.GetSelection()
            if selection != wx.NOT_FOUND:
                previous_managed = self.list_presets.GetClientData(selection)
            self.list_presets.Clear()
        self.combo_presets.Clear()
        self.combo_presets.Append(self._("no_preset"), None)

        if PRESETS_DIR.exists():
            pts = []
            for candidate in PRESETS_DIR.iterdir():
                if candidate.suffix.lower() != ".pt":
                    continue
                try:
                    safe_path = safe_child_path(PRESETS_DIR, candidate.name)
                    if safe_path.is_file():
                        pts.append(candidate.name)
                except (OSError, ValueError) as exc:
                    logging.warning("Ignoring unsafe preset %s: %s", candidate, exc)

            pts.sort(key=str.casefold)
            display_mode = self.cfg.get("preset_display_mode", "name")

            for pt in pts:
                name_only = os.path.splitext(pt)[0]
                full_path = str(safe_child_path(PRESETS_DIR, pt))

                if display_mode == "name":
                    disp = name_only
                elif display_mode == "path":
                    disp = full_path
                else:  # name_path
                    disp = f"{name_only} ({full_path})"

                self.combo_presets.Append(disp, pt)
                if hasattr(self, "list_presets"):
                    self.list_presets.Append(disp, pt)

        self.combo_presets.SetSelection(0)
        if hasattr(self, "list_presets") and self.list_presets.GetCount():
            selection = 0
            if previous_managed:
                for index in range(self.list_presets.GetCount()):
                    if self.list_presets.GetClientData(index) == previous_managed:
                        selection = index
                        break
            self.list_presets.SetSelection(selection)
        if not (self.current_op and not self.current_op.finished):
            self._set_operation_controls_enabled(True)

    def Log(self, msg, success=False):
        self.status_text.AppendText(msg + "\n")
        if success and self.cfg.get("confirm_success", False):
            wx.CallAfter(
                lambda: wx.MessageBox(msg, self._("success_title"), wx.OK | wx.ICON_INFORMATION)
            )

    def AutoLoadModel(self):
        if not self.model:
            self.OnToggleModel(None)

    def OnToggleModel(self, event):
        if self.model is None:

            def on_success(model):
                self.model = model
                self.sample_rate = int(getattr(model, "sampling_rate", 24000) or 24000)
                self.btn_toggle_model.SetLabel(self._("unload_model"))
                self.Log(self._("model_loaded"), success=True)
                self.clone_text.SetFocus()
                wx.Bell()

            self.RunOperation(
                "op_load_title", "op_load_msg", self._LoadModelWorker, success_callback=on_success
            )
        else:

            def on_success(_result):
                self.model = None
                if torch and torch.cuda.is_available():
                    torch.cuda.empty_cache()
                self.btn_toggle_model.SetLabel(self._("load_model"))
                self.Log(self._("model_unloaded"), success=True)
                wx.Bell()

            self.RunOperation(
                "op_unload_title",
                "op_unload_msg",
                self._UnloadModelWorker,
                success_callback=on_success,
            )

    def _LoadModelWorker(self, state):
        state.check_cancelled()
        device = get_best_device()
        dtype = torch.float16 if str(device).startswith(("cuda", "xpu")) else torch.float32
        kwargs = {
            "device_map": device,
            "dtype": dtype,
            "load_asr": self.cfg.get("preload_asr", False),
        }
        asr_name = self.cfg.get("asr_model_name")
        if asr_name:
            kwargs["asr_model_name"] = asr_name
        model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", **kwargs)
        state.check_cancelled()
        return model

    def _UnloadModelWorker(self, state):
        state.check_cancelled()
        return True

    def GetGenConfig(self):
        return OmniVoiceGenerationConfig(
            num_step=self.spin_steps.GetValue(),
            guidance_scale=self.spin_cfg.GetValue(),
            denoise=self.chk_denoise.GetValue(),
            t_shift=self.spin_t_shift.GetValue(),
            layer_penalty_factor=self.spin_layer_penalty.GetValue(),
            position_temperature=self.spin_position_temperature.GetValue(),
            class_temperature=self.spin_class_temperature.GetValue(),
            preprocess_prompt=self.chk_preprocess_prompt.GetValue(),
            postprocess_output=self.chk_postprocess_output.GetValue(),
            audio_chunk_duration=self.spin_chunk_duration.GetValue(),
            audio_chunk_threshold=self.spin_chunk_threshold.GetValue(),
            pad_duration=self.spin_pad_duration.GetValue(),
            fade_duration=self.spin_fade_duration.GetValue(),
        )

    def _prepare_generation(self):
        self.OnStopAudio(None)
        self.audio_data = None
        self.btn_play.Disable()
        self.btn_save.Disable()
        self.item_play_pause.Enable(False)
        self.item_save_result.Enable(False)

    def _finish_generation(self, audio):
        audio_array = np.asarray(audio)
        if audio_array.ndim != 1 or audio_array.size == 0 or not np.isfinite(audio_array).all():
            raise ValueError(self._("invalid_generated_audio"))
        self.audio_data = audio_array
        self.Log(self._("ready"), success=True)
        self.btn_play.Enable()
        self.btn_save.Enable()
        self.item_play_pause.Enable()
        self.item_save_result.Enable()
        self.btn_play.SetFocus()
        wx.Bell()
        if self.cfg.get("auto_save_gen", False):
            try:
                self.PerformSaveAudio(audio, self.sample_rate, is_generated=True)
            except Exception as exc:
                wx.MessageBox(
                    self._("save_failed").format(error=str(exc)),
                    self._("error_title"),
                    wx.OK | wx.ICON_ERROR,
                )

    def OnGenClone(self, event):
        if not self.model:
            wx.MessageBox(self._("msg_load_first"), self._("error_title"))
            return

        text = self.clone_text.GetValue().strip()
        lang = self.clone_lang.GetValue()
        if lang == "Auto":
            lang = None

        ref_text = self.clone_ref_text.GetValue().strip() or None
        ref_audio = self.clone_ref_audio.GetValue().strip()
        instruct = self.clone_instruct.GetValue().strip() or None
        preset_idx = self.combo_presets.GetSelection()
        preset = (
            self.combo_presets.GetClientData(preset_idx) if preset_idx != wx.NOT_FOUND else None
        )
        speed = self.spin_speed.GetValue()
        duration = self.spin_duration.GetValue() if self.chk_duration.GetValue() else None
        norm_txt = self.cfg.get("normalize_text", False)
        gen_config = self.GetGenConfig()

        if not text:
            wx.MessageBox(self._("err_no_text"), self._("error_title"), wx.OK | wx.ICON_ERROR)
            return

        use_preset = preset is not None
        if not use_preset and not os.path.exists(ref_audio):
            wx.MessageBox(
                self._("err_no_audio_preset"), self._("error_title"), wx.OK | wx.ICON_ERROR
            )
            return

        try:
            preset_path = str(safe_child_path(PRESETS_DIR, preset)) if use_preset else None
        except ValueError as exc:
            wx.MessageBox(
                self._("invalid_filename").format(error=str(exc)),
                self._("error_title"),
                wx.OK | wx.ICON_ERROR,
            )
            return

        self._prepare_generation()
        self.RunOperation(
            "op_gen_title",
            "op_gen_msg",
            self._GenCloneWorker,
            self.model,
            gen_config,
            text,
            ref_audio,
            preset_path,
            ref_text,
            lang,
            instruct,
            speed,
            duration,
            norm_txt,
            success_callback=self._finish_generation,
        )

    def _GenCloneWorker(
        self,
        state,
        model,
        gen_config,
        text,
        ref_audio,
        preset_path,
        ref_text,
        lang,
        instruct,
        speed,
        duration,
        norm_txt,
    ):
        state.check_cancelled()
        if preset_path:
            prompt = VoiceClonePrompt.load(preset_path)
        else:
            prompt = model.create_voice_clone_prompt(
                ref_audio=ref_audio,
                ref_text=ref_text,
                preprocess_prompt=gen_config.preprocess_prompt,
            )
        state.check_cancelled()
        kwargs = {
            "text": text,
            "generation_config": gen_config,
            "voice_clone_prompt": prompt,
            "normalize_text": norm_txt,
        }
        if lang:
            kwargs["language"] = lang
        if instruct:
            kwargs["instruct"] = instruct
        if duration:
            kwargs["duration"] = duration
        else:
            kwargs["speed"] = speed
        audio = model.generate(**kwargs)
        state.check_cancelled()
        return audio[0]

    def SetupAutoTab(self, tab):
        vbox = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(tab, label=self._("auto_text_lbl"))
        vbox.Add(label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.auto_text = wx.TextCtrl(tab, style=wx.TE_MULTILINE)
        vbox.Add(self.auto_text, 1, wx.EXPAND | wx.ALL, 5)

        hbox = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(tab, label=self._("auto_lang_lbl"))
        hbox.Add(label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.auto_lang = wx.ComboBox(tab, choices=_ALL_LANGUAGES, style=wx.CB_READONLY)
        self.auto_lang.SetValue(
            self.cfg.get("auto_lang", "Auto")
            if self.cfg.get("remember_ai_settings", True)
            and self.cfg.get("auto_lang", "Auto") in _ALL_LANGUAGES
            else "Auto"
        )
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
        if lang == "Auto":
            lang = None
        speed = self.spin_speed.GetValue()
        duration = self.spin_duration.GetValue() if self.chk_duration.GetValue() else None
        norm_txt = self.cfg.get("normalize_text", False)
        gen_config = self.GetGenConfig()
        if not text:
            wx.MessageBox(self._("err_no_text"), self._("error_title"), wx.OK | wx.ICON_ERROR)
            return

        self._prepare_generation()
        self.RunOperation(
            "op_auto_title",
            "op_auto_msg",
            self._GenAutoWorker,
            self.model,
            gen_config,
            text,
            lang,
            speed,
            duration,
            norm_txt,
            success_callback=self._finish_generation,
        )

    def _GenAutoWorker(self, state, model, gen_config, text, lang, speed, duration, norm_txt):
        state.check_cancelled()
        kwargs = {"text": text, "generation_config": gen_config, "normalize_text": norm_txt}
        if lang:
            kwargs["language"] = lang
        if duration:
            kwargs["duration"] = duration
        else:
            kwargs["speed"] = speed
        audio = model.generate(**kwargs)
        state.check_cancelled()
        return audio[0]

    def OnGenDesign(self, event):
        if not self.model:
            wx.MessageBox(self._("msg_load_first"), self._("error_title"))
            return
        text = self.design_text.GetValue().strip()
        lang = self.design_lang.GetValue()
        if lang == "Auto":
            lang = None
        speed = self.spin_speed.GetValue()
        duration = self.spin_duration.GetValue() if self.chk_duration.GetValue() else None
        norm_txt = self.cfg.get("normalize_text", False)
        gen_config = self.GetGenConfig()
        if not text:
            wx.MessageBox(self._("err_no_text"), self._("error_title"), wx.OK | wx.ICON_ERROR)
            return

        instructs = []
        for c in self.design_combos:
            idx = c.GetSelection()
            if idx != wx.NOT_FOUND:
                eng_val = c.GetClientData(idx)
                if eng_val != "None":
                    instructs.append(eng_val)

        custom_instruct = self.design_custom_instruct.GetValue().strip()
        if custom_instruct:
            instructs.append(custom_instruct)

        instruct = ", ".join(instructs) if instructs else None

        self._prepare_generation()
        self.RunOperation(
            "op_gen_title",
            "op_gen_msg",
            self._GenDesignWorker,
            self.model,
            gen_config,
            text,
            lang,
            instruct,
            speed,
            duration,
            norm_txt,
            success_callback=self._finish_generation,
        )

    def _GenDesignWorker(
        self, state, model, gen_config, text, lang, instruct, speed, duration, norm_txt
    ):
        state.check_cancelled()
        kwargs = {
            "text": text,
            "instruct": instruct,
            "generation_config": gen_config,
            "normalize_text": norm_txt,
        }
        if lang:
            kwargs["language"] = lang
        if duration:
            kwargs["duration"] = duration
        else:
            kwargs["speed"] = speed
        audio = model.generate(**kwargs)
        state.check_cancelled()
        return audio[0]

    def OnSavePresetPrompt(self, event):
        ref_audio = self.clone_ref_audio.GetValue().strip()
        ref_text = self.clone_ref_text.GetValue().strip() or None
        self._PromptAndSavePreset(ref_audio, ref_text)

    def OnSaveManagedPreset(self, event):
        ref_audio = self.preset_source_audio.GetValue().strip()
        ref_text = self.preset_source_ref_text.GetValue().strip() or None
        self._PromptAndSavePreset(ref_audio, ref_text)

    def _PromptAndSavePreset(self, ref_audio, ref_text):
        if not self.model:
            wx.MessageBox(self._("msg_load_first"), self._("error_title"))
            return

        if not os.path.isfile(ref_audio):
            wx.MessageBox(
                self._("err_file_not_found"), self._("error_title"), wx.OK | wx.ICON_ERROR
            )
            return

        dialog = wx.TextEntryDialog(self, self._("prompt_preset_name"), self._("preset_name_title"))
        if dialog.ShowModal() == wx.ID_OK:
            try:
                filename = preset_filename(dialog.GetValue())
                path = safe_child_path(PRESETS_DIR, filename)
            except ValueError as exc:
                wx.MessageBox(
                    self._("invalid_filename").format(error=str(exc)),
                    self._("error_title"),
                    wx.OK | wx.ICON_ERROR,
                )
                dialog.Destroy()
                return

            if not self._ConfirmPresetOverwrite(path):
                dialog.Destroy()
                return

            self._StartPresetRebuild(ref_audio, ref_text, path)
        dialog.Destroy()

    def _ConfirmPresetOverwrite(self, path, original_path=None):
        if not path.exists() or (original_path is not None and path == original_path):
            return True
        return (
            wx.MessageBox(
                self._("overwrite_preset").format(name=path.stem),
                self._("warning_title"),
                wx.YES_NO | wx.ICON_WARNING,
            )
            == wx.YES
        )

    def _PresetSaved(self, saved_path):
        path = safe_child_path(PRESETS_DIR, os.path.basename(saved_path))
        self.Log(self._("preset_saved").format(path=saved_path))
        self.RefreshPresets()
        msg = self._("preset_created_msg").replace("{name}", path.stem)
        if self.cfg.get("confirm_success", False):
            wx.MessageBox(msg, self._("success_title"), wx.OK | wx.ICON_INFORMATION)

    def _StartPresetRebuild(self, ref_audio, ref_text, path, original_path=None):
        self.RunOperation(
            "op_preset_title",
            "op_preset_msg",
            self._SavePresetWorker,
            self.model,
            ref_audio,
            ref_text,
            path,
            self.chk_preprocess_prompt.GetValue(),
            original_path,
            success_callback=self._PresetSaved,
        )

    @staticmethod
    def _SavePromptAtomically(state, prompt, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.tmp")
        try:
            prompt.save(str(temp_path))
            state.check_cancelled()
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _SavePresetWorker(
        self, state, model, ref_audio, ref_text, path, preprocess_prompt, original_path=None
    ):
        state.check_cancelled()
        prompt = model.create_voice_clone_prompt(
            ref_audio=ref_audio,
            ref_text=ref_text,
            preprocess_prompt=preprocess_prompt,
        )
        state.check_cancelled()
        self._SavePromptAtomically(state, prompt, path)
        if original_path is not None and original_path != path:
            original_path.unlink(missing_ok=True)
        return str(path)

    def _SelectedManagedPreset(self, show_error=True):
        selection = self.list_presets.GetSelection()
        preset = self.list_presets.GetClientData(selection) if selection != wx.NOT_FOUND else None
        if not preset:
            if show_error:
                wx.MessageBox(
                    self._("msg_no_preset_sel"), self._("error_title"), wx.OK | wx.ICON_ERROR
                )
            return None
        try:
            return safe_child_path(PRESETS_DIR, preset)
        except ValueError as exc:
            if show_error:
                wx.MessageBox(str(exc), self._("error_title"), wx.OK | wx.ICON_ERROR)
            return None

    def OnEditPreset(self, event):
        original_path = self._SelectedManagedPreset()
        if original_path is None:
            return

        try:
            prompt = VoiceClonePrompt.load(str(original_path))
        except Exception as exc:
            wx.MessageBox(
                self._("preset_load_failed").format(error=str(exc)),
                self._("error_title"),
                wx.OK | wx.ICON_ERROR,
            )
            return

        dialog = PresetEditDialog(self, self._, original_path.stem, prompt.ref_text)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return

        try:
            target_path = safe_child_path(PRESETS_DIR, preset_filename(dialog.name_ctrl.GetValue()))
        except ValueError as exc:
            dialog.Destroy()
            wx.MessageBox(
                self._("invalid_filename").format(error=str(exc)),
                self._("error_title"),
                wx.OK | wx.ICON_ERROR,
            )
            return

        source_audio = dialog.source_ctrl.GetValue().strip()
        ref_text = dialog.ref_text_ctrl.GetValue().strip()
        dialog.Destroy()

        if not self._ConfirmPresetOverwrite(target_path, original_path):
            return

        if source_audio:
            if not self.model:
                wx.MessageBox(self._("msg_load_first"), self._("error_title"))
                return
            if not os.path.isfile(source_audio):
                wx.MessageBox(
                    self._("err_file_not_found"), self._("error_title"), wx.OK | wx.ICON_ERROR
                )
                return
            self._StartPresetRebuild(
                source_audio,
                ref_text or None,
                target_path,
                original_path=original_path,
            )
            return

        prompt.ref_text = ref_text
        self.RunOperation(
            "op_preset_title",
            "op_preset_msg",
            self._UpdatePresetWorker,
            prompt,
            target_path,
            original_path,
            success_callback=self._PresetSaved,
        )

    def _UpdatePresetWorker(self, state, prompt, path, original_path):
        state.check_cancelled()
        self._SavePromptAtomically(state, prompt, path)
        if original_path != path:
            original_path.unlink(missing_ok=True)
        return str(path)

    def _CheckDeleteWarning(self, msg):
        if not self.cfg.get("warn_delete_preset", True):
            return True
        dlg = wx.RichMessageDialog(self, msg, self._("warning_title"), wx.YES_NO | wx.ICON_WARNING)
        dlg.ShowCheckBox(self._("warn_no_show"))
        res = dlg.ShowModal()
        if dlg.IsCheckBoxChecked():
            self.cfg["warn_delete_preset"] = False
            SaveBasicConfig(self.cfg)
        dlg.Destroy()
        return res == wx.ID_YES

    def OnDelPreset(self, event):
        path = self._SelectedManagedPreset()
        if path is None:
            return

        if not self._CheckDeleteWarning(self._("warn_del_preset").replace("{name}", path.stem)):
            return

        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                wx.MessageBox(str(exc), self._("error_title"), wx.OK | wx.ICON_ERROR)
                return
        self.RefreshPresets()

    def OnDelAllPresets(self, event):
        if not self._CheckDeleteWarning(self._("warn_del_all")):
            return

        if PRESETS_DIR.exists():
            for f in os.listdir(PRESETS_DIR):
                if f.lower().endswith(".pt"):
                    try:
                        safe_child_path(PRESETS_DIR, f).unlink(missing_ok=True)
                    except (OSError, ValueError) as exc:
                        wx.MessageBox(str(exc), self._("error_title"), wx.OK | wx.ICON_ERROR)
                        return
        self.RefreshPresets()
        wx.MessageBox(
            self._("msg_presets_deleted"), self._("success_title"), wx.OK | wx.ICON_INFORMATION
        )

    def OnPresetManagerKeyDown(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_DELETE:
            path = self._SelectedManagedPreset(show_error=False)
            if path is None:
                event.Skip()
                return

            try:
                if event.ShiftDown():
                    if path.exists():
                        path.unlink()
                    self.RefreshPresets()
                else:
                    if self._CheckDeleteWarning(
                        self._("warn_del_preset").replace("{name}", path.stem)
                    ):
                        if path.exists():
                            path.unlink()
                        self.RefreshPresets()
            except (OSError, ValueError) as exc:
                wx.MessageBox(str(exc), self._("error_title"), wx.OK | wx.ICON_ERROR)
        else:
            event.Skip()

    def _stop_sound_device(self):
        if sd:
            try:
                sd.stop()
            except Exception as exc:
                logging.warning("Could not stop audio playback: %s", exc)

    def _play_sound_data(self, data, sample_rate):
        try:
            sd.play(data, samplerate=sample_rate)
            return True
        except Exception as exc:
            wx.MessageBox(
                self._("err_playback").format(e=str(exc)),
                self._("error_title"),
                wx.OK | wx.ICON_ERROR,
            )
            return False

    def _reset_generated_player(self):
        timer = getattr(self, "play_timer", None)
        if timer:
            timer.Stop()
        self.play_timer = None
        self.play_start_time = None
        self.is_paused = False
        self.current_frame = 0
        if hasattr(self, "btn_play"):
            self.btn_play.SetLabel(self._("play"))
        if hasattr(self, "btn_stop_audio"):
            self.btn_stop_audio.Hide()

    def _reset_reference_player(self):
        button = getattr(self, "btn_play_ref", None)
        if button:
            timer = getattr(self, f"timer_{id(button)}", None)
            if timer:
                timer.Stop()
            setattr(self, f"timer_{id(button)}", None)
            button.SetLabel(self._("play_ref"))
        if hasattr(self, "btn_stop_ref"):
            self.btn_stop_ref.Hide()
        self.ref_current_frame = 0

    def OnPlayAudio(self, event):
        import time

        if self.btn_play.GetLabel() == self._("play"):
            if self.audio_data is not None and sd:
                self.OnStopAudio(None)
                self.current_frame = 0
                self.total_frames = len(self.audio_data)
                self.is_paused = False

                frames_left = self.total_frames - self.current_frame
                if not self._play_sound_data(
                    self.audio_data[self.current_frame :], self.sample_rate
                ):
                    return

                self.btn_play.SetLabel(self._("pause"))
                self.btn_stop_audio.Show()
                self.panel.Layout()

                duration_ms = int((frames_left / self.sample_rate) * 1000)
                if hasattr(self, "play_timer") and self.play_timer:
                    self.play_timer.Stop()

                def on_finish():
                    self._reset_generated_player()
                    self.panel.Layout()

                self.play_start_time = time.time()
                self.play_timer = wx.CallLater(duration_ms + 100, on_finish)

        elif self.btn_play.GetLabel() == self._("pause"):
            self.is_paused = True
            if hasattr(self, "play_timer") and self.play_timer:
                if hasattr(self, "play_start_time") and self.play_start_time:
                    elapsed = time.time() - self.play_start_time
                    self.current_frame += int(elapsed * self.sample_rate)
                self.play_timer.Stop()
            self._stop_sound_device()
            self.btn_play.SetLabel(self._("resume_play"))

        elif self.btn_play.GetLabel() == self._("resume_play"):
            self.is_paused = False
            frames_left = self.total_frames - self.current_frame
            if not self._play_sound_data(self.audio_data[self.current_frame :], self.sample_rate):
                self._reset_generated_player()
                return
            self.btn_play.SetLabel(self._("pause"))

            duration_ms = int((frames_left / self.sample_rate) * 1000)
            if hasattr(self, "play_timer") and self.play_timer:
                self.play_timer.Stop()

            def on_finish():
                self._reset_generated_player()
                self.panel.Layout()

            self.play_start_time = time.time()
            self.play_timer = wx.CallLater(duration_ms + 100, on_finish)

    def OnStopAudio(self, event):
        self._stop_sound_device()
        self._reset_generated_player()
        self._reset_reference_player()
        self.panel.Layout()

    def PerformSaveAudio(self, data, fs, is_generated=True, force_dialog=False):
        if is_generated:
            skip_dialog = self.cfg.get("auto_save_gen_folder", False) and not force_dialog
            prefix = self.cfg.get("prefix_gen", "generated")
            folder = default_audio_directory("generated")
        else:
            skip_dialog = self.cfg.get("auto_save_rec_folder", False) and not force_dialog
            prefix = self.cfg.get("prefix_rec", "record")
            folder = default_audio_directory("recorded")

        prefix = validate_filename_component(prefix, label="audio prefix")
        folder.mkdir(parents=True, exist_ok=True)
        idx = 1
        while True:
            fname = f"{prefix}_{idx}.wav"
            suggested_path = safe_child_path(folder, fname)
            if not suggested_path.exists():
                break
            idx += 1

        if skip_dialog:
            path = suggested_path
            sf.write(str(path), data, fs)
            if self.cfg.get("confirm_success", False):
                wx.MessageBox(
                    self._("msg_save_ok") + f"\n{path}",
                    self._("title_save"),
                    wx.OK | wx.ICON_INFORMATION,
                )
            return str(path)
        else:
            with wx.FileDialog(
                self,
                self._("save"),
                defaultDir=str(folder),
                defaultFile=fname,
                wildcard="WAV (*.wav)|*.wav",
                style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
            ) as fd:
                if fd.ShowModal() != wx.ID_CANCEL:
                    path = fd.GetPath()
                    sf.write(path, data, fs)
                    if self.cfg.get("confirm_success", False):
                        wx.MessageBox(
                            self._("msg_save_ok") + f"\n{path}",
                            self._("title_save"),
                            wx.OK | wx.ICON_INFORMATION,
                        )
                    return path
        return None

    def OnSaveAudio(self, event):
        if self.audio_data is not None:
            self.OnStopAudio(None)
            try:
                self.PerformSaveAudio(
                    self.audio_data,
                    self.sample_rate,
                    is_generated=True,
                    force_dialog=True,
                )
            except Exception as exc:
                wx.MessageBox(
                    self._("save_failed").format(error=str(exc)),
                    self._("error_title"),
                    wx.OK | wx.ICON_ERROR,
                )

    def TogglePlayFile(self, btn_play, path_ctrl, btn_stop, parent_tab):
        import time

        if btn_play.GetLabel() == self._("play_ref"):
            path = path_ctrl.GetValue().strip()
            if not os.path.exists(path):
                wx.MessageBox(
                    self._("err_file_not_found"), self._("error_title"), wx.OK | wx.ICON_ERROR
                )
                return
            try:
                self.OnStopAudio(None)
                waveform, fs = load_waveform(path)
                data = waveform[0] if waveform.shape[0] == 1 else waveform.T
                self.ref_audio_data = data
                self.ref_sample_rate = fs
                self.ref_current_frame = 0
                self.ref_total_frames = len(data)

                if not self._play_sound_data(
                    self.ref_audio_data[self.ref_current_frame :], self.ref_sample_rate
                ):
                    return
                btn_play.SetLabel(self._("pause"))
                btn_stop.Show()
                parent_tab.Layout()

                duration_ms = int((self.ref_total_frames / fs) * 1000)
                timer = wx.CallLater(
                    duration_ms + 100, lambda: self.StopPlayFile(btn_play, btn_stop, parent_tab)
                )
                setattr(self, f"timer_{id(btn_play)}", timer)
                setattr(self, f"start_{id(btn_play)}", time.time())

            except Exception as e:
                wx.MessageBox(
                    self._("err_playback").format(e=str(e)),
                    self._("error_title"),
                    wx.OK | wx.ICON_ERROR,
                )

        elif btn_play.GetLabel() == self._("pause"):
            timer = getattr(self, f"timer_{id(btn_play)}", None)
            if timer:
                start_time = getattr(self, f"start_{id(btn_play)}", None)
                if start_time:
                    elapsed = time.time() - start_time
                    self.ref_current_frame += int(elapsed * self.ref_sample_rate)
                timer.Stop()
            self._stop_sound_device()
            btn_play.SetLabel(self._("resume_play"))

        elif btn_play.GetLabel() == self._("resume_play"):
            frames_left = self.ref_total_frames - self.ref_current_frame
            if not self._play_sound_data(
                self.ref_audio_data[self.ref_current_frame :], self.ref_sample_rate
            ):
                self._reset_reference_player()
                return
            btn_play.SetLabel(self._("pause"))

            duration_ms = int((frames_left / self.ref_sample_rate) * 1000)
            timer = wx.CallLater(
                duration_ms + 100, lambda: self.StopPlayFile(btn_play, btn_stop, parent_tab)
            )
            setattr(self, f"timer_{id(btn_play)}", timer)
            setattr(self, f"start_{id(btn_play)}", time.time())

    def StopPlayFile(self, btn_play, btn_stop, parent_tab):
        self._stop_sound_device()
        self._reset_reference_player()
        self._reset_generated_player()
        parent_tab.Layout()

    def ToggleRecord(self, btn, path_ctrl):
        if btn.GetLabel() == self._("rec_ref"):
            try:
                btn.SetLabel(self._("stop_rec"))
                self.rec_data = []
                self.rec_fs = 24000

                def callback(indata, frames, time_info, status):
                    if status:
                        logging.warning("Audio input status: %s", status)
                    self.rec_data.append(indata.copy())

                self.rec_stream = sd.InputStream(
                    samplerate=self.rec_fs, channels=1, callback=callback
                )
                self.rec_stream.start()
            except Exception as exc:
                btn.SetLabel(self._("rec_ref"))
                wx.MessageBox(
                    self._("record_failed").format(error=str(exc)),
                    self._("error_title"),
                    wx.OK | wx.ICON_ERROR,
                )
        else:
            btn.SetLabel(self._("rec_ref"))
            try:
                if hasattr(self, "rec_stream") and self.rec_stream:
                    self.rec_stream.stop()
                    self.rec_stream.close()
                    self.rec_stream = None

                if hasattr(self, "rec_data") and self.rec_data:
                    audio = np.concatenate(self.rec_data, axis=0)
                    RECORDED_AUDIO_FILE.parent.mkdir(parents=True, exist_ok=True)
                    sf.write(str(RECORDED_AUDIO_FILE), audio, self.rec_fs)
                    path_ctrl.SetValue(str(RECORDED_AUDIO_FILE))
                    wx.Bell()
                    if self.cfg.get("auto_save_rec", False):
                        self.PerformSaveAudio(audio, self.rec_fs, is_generated=False)
                else:
                    raise RuntimeError(self._("record_empty"))
            except Exception as exc:
                wx.MessageBox(
                    self._("record_failed").format(error=str(exc)),
                    self._("error_title"),
                    wx.OK | wx.ICON_ERROR,
                )

    def OnShowTags(self, event):
        wx.MessageBox(self._("msg_tags"), self._("title_tags"), wx.OK | wx.ICON_INFORMATION)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    app = wx.App(False)

    try:
        migrate_legacy_user_data()
    except OSError as exc:
        logging.exception("Could not initialize the OmniSonic user-data directory")
        wx.MessageBox(
            translate(LOCALE, "en", "user_data_error").format(error=str(exc)),
            translate(LOCALE, "en", "error_title"),
            wx.OK | wx.ICON_ERROR,
        )
        return 1

    cfg = LoadBasicConfig()
    SetConsoleVisible(not cfg.get("hide_console", True))

    if not cfg.get("first_run_done", False):
        dlg = SettingsDialog(None, is_first_run=True, current_cfg=cfg)
        if dlg.ShowModal() == wx.ID_OK:
            cfg = dlg.cfg
            try:
                SaveBasicConfig(cfg)
            except OSError as exc:
                wx.MessageBox(
                    translate(LOCALE, cfg.get("language", "en"), "config_save_failed").format(
                        error=str(exc)
                    ),
                    translate(LOCALE, cfg.get("language", "en"), "error_title"),
                    wx.OK | wx.ICON_ERROR,
                )
                dlg.Destroy()
                return 1
        else:
            dlg.Destroy()
            return 0
        dlg.Destroy()

    if cfg.get("hide_console", True) or cfg.get("force_splash"):
        splash = StartupSplash(None, cfg)
        if splash.ShowModal() != wx.ID_OK:
            return 1
    else:
        try:
            LoadRuntimeDependencies()
        except Exception as exc:
            logging.exception("Could not load OmniSonic runtime dependencies")
            wx.MessageBox(
                translate(LOCALE, cfg.get("language", "en"), "startup_error").format(
                    error=str(exc)
                ),
                translate(LOCALE, cfg.get("language", "en"), "error_title"),
                wx.OK | wx.ICON_ERROR,
            )
            return 1

    frame = OmniVoiceFrame(cfg, None)
    frame.Show(True)
    app.MainLoop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
