"""Windows wx smoke test for dark surfaces and reversible theme previews."""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    scratch = Path(tempfile.mkdtemp(prefix="theme-ui-", dir=root / "trash"))
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG
    from omnisonic.theme import (
        DARK_ACCENT,
        DARK_BUTTON,
        DARK_FIELD,
        DARK_SURFACE,
        DARK_TEXT,
        LIGHT_BUTTON,
        LIGHT_FIELD,
        LIGHT_SURFACE,
        LIGHT_TEXT,
    )

    def contrast(first, second):
        def luminance(colour):
            channels = [colour.Red(), colour.Green(), colour.Blue()]
            linear = [
                value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
                for value in (channel / 255 for channel in channels)
            ]
            return sum(
                weight * value
                for weight, value in zip((0.2126, 0.7152, 0.0722), linear, strict=True)
            )

        lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
        return (lighter + 0.05) / (darker + 0.05)

    for foreground, background in (
        (DARK_TEXT, DARK_SURFACE),
        (DARK_TEXT, DARK_FIELD),
        (DARK_TEXT, DARK_BUTTON),
        (LIGHT_TEXT, LIGHT_SURFACE),
        (LIGHT_TEXT, LIGHT_FIELD),
        (LIGHT_TEXT, LIGHT_BUTTON),
    ):
        assert contrast(foreground, background) >= 7

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

    def coloured(window, surface):
        assert window.GetBackgroundColour() == surface, (
            type(window).__name__,
            window.GetBackgroundColour(),
            surface,
        )
        assert window.GetForegroundColour() == DARK_TEXT

    wx_app = wx.App(False)
    cfg = dict(DEFAULT_CONFIG, theme="dark")
    frame = TestFrame(cfg, None)
    wx_app.SetTopWindow(frame)
    try:
        coloured(frame, DARK_SURFACE)
        coloured(frame.clone_ref_audio, DARK_FIELD)
        coloured(frame.btn_toggle_model, DARK_BUTTON)
        assert frame.batch_list.GetTextColour() == DARK_TEXT
        assert frame.gauge.GetForegroundColour() == DARK_ACCENT
        assert frame.clone_ref_audio.GetName()
        assert frame.btn_toggle_model.GetName() or frame.btn_toggle_model.GetLabel()

        settings = desktop.SettingsDialog(frame, current_cfg=dict(cfg))
        try:
            coloured(settings, DARK_SURFACE)
            coloured(settings.cb_theme, DARK_FIELD)
            coloured(settings.cb_asr, DARK_FIELD)
            coloured(settings.btn_ok, DARK_BUTTON)
            coloured(settings.chk_auto_transcribe, DARK_SURFACE)
            assert settings.cb_theme.GetName() == settings._("theme_lbl")
            assert settings.btn_ok.GetLabel() == settings._("btn_save")
            settings.cb_theme.SetFocus()
            assert wx.Window.FindFocus() == settings.cb_theme

            settings.cb_theme.SetSelection(0)
            settings.OnThemeChange(None)
            assert settings.GetBackgroundColour() == LIGHT_SURFACE
            assert settings.cb_theme.GetBackgroundColour() == LIGHT_FIELD
            assert settings.cb_theme.GetForegroundColour() == LIGHT_TEXT
            assert settings.btn_ok.GetBackgroundColour() == LIGHT_BUTTON
            assert frame.GetBackgroundColour() == DARK_SURFACE  # Preview is local.

            settings.cb_theme.SetSelection(1)
            settings.OnThemeChange(None)
            coloured(settings.cb_theme, DARK_FIELD)
            capture_dialog = desktop.ShortcutCaptureDialog(settings, settings._)
            try:
                coloured(capture_dialog, DARK_SURFACE)
                assert capture_dialog.instructions.GetName()
            finally:
                capture_dialog.Destroy()

            with patch.object(desktop.DownloadDialog, "_run_download"):
                download = desktop.DownloadDialog(
                    settings, "Download", "Downloading", "example/model", settings._
                )
                try:
                    download.timer.Stop()
                    coloured(download, DARK_SURFACE)
                    coloured(download.btn_cancel, DARK_BUTTON)
                finally:
                    download.Destroy()
        finally:
            settings.Destroy()

        editor = desktop.PresetEditDialog(frame, frame._, "Test", "Transcript")
        try:
            coloured(editor.name_ctrl, DARK_FIELD)
            coloured(editor.ref_text_ctrl, DARK_FIELD)
        finally:
            editor.Destroy()

        # Modal startup/progress windows must receive the same palette too.
        gate = threading.Event()
        startup = desktop.StartupSplash(frame, cfg)
        startup_seen = []

        def inspect_startup():
            try:
                coloured(startup.dialog, DARK_SURFACE)
                coloured(startup.label, DARK_SURFACE)
                coloured(startup.cancel_button, DARK_BUTTON)
                startup_seen.append(True)
            finally:
                gate.set()

        with patch.object(desktop, "LoadRuntimeDependencies", side_effect=lambda: gate.wait(5)):
            wx.CallLater(100, inspect_startup)
            assert startup.ShowModal() == wx.ID_OK
        assert startup_seen

        gate = threading.Event()
        operation = desktop.OperationDialog(
            frame, cfg, "startup_title", "startup_msg", lambda state: gate.wait(5)
        )
        operation_seen = []

        def inspect_operation():
            try:
                coloured(operation.dialog, DARK_SURFACE)
                coloured(operation.cancel_button, DARK_BUTTON)
                operation_seen.append(True)
            finally:
                gate.set()

        wx.CallLater(100, inspect_operation)
        assert operation.ShowModal().succeeded
        assert operation_seen

        frame.cfg["theme"] = "light"
        frame.ApplyTheme()
        assert frame.GetBackgroundColour() == LIGHT_SURFACE
        assert frame.clone_ref_audio.GetBackgroundColour() == LIGHT_FIELD
        assert frame.btn_toggle_model.GetBackgroundColour() == LIGHT_BUTTON
        assert frame.batch_list.GetTextColour() == LIGHT_TEXT
        frame.cfg["theme"] = "dark"
        frame.ApplyTheme()
        coloured(frame.btn_toggle_model, DARK_BUTTON)
    finally:
        frame.Destroy()
        wx_app.Yield()
    print("Theme smoke test passed: frame, modal dialogs, preview and light/dark reversal")


if __name__ == "__main__":
    main()
