"""Read the real tag dialog in both locales/themes with no model or user profile."""

from __future__ import annotations

import os
from pathlib import Path

from tests.materials import scratch_directory


def main():
    scratch = scratch_directory("tag-help-wx-")
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import wx

    from omnisonic.help_dialogs import ReadOnlyTextDialog
    from omnisonic.i18n import load_locales, translate
    from omnisonic.theme import DARK_FIELD, LIGHT_FIELD

    application = wx.App(False)
    application.SetExitOnFrameDelete(False)
    parent = wx.Frame(None, title="Owned tag help test")
    editor = wx.TextCtrl(parent, value="Original input")
    parent.Show()
    application.Yield()
    editor.SetFocus()
    locales = load_locales((Path(__file__).resolve().parents[1] / "langs",))
    failures = []
    checks = []
    try:
        for language in ("pl", "en"):
            for theme, colour in (("dark", DARK_FIELD), ("light", LIGHT_FIELD)):
                assert wx.Window.FindFocus() is editor
                parent.cfg = {"theme": theme, "font_size": 16}

                def label(key, language=language):
                    return translate(locales, language, key)

                dialog = ReadOnlyTextDialog(
                    parent,
                    label("title_tags"),
                    label("msg_tags"),
                    label("btn_close"),
                    font_size=16,
                )

                def check(
                    dialog=dialog, label=label, colour=colour, language=language, theme=theme
                ):
                    try:
                        assert wx.Window.FindFocus() is dialog.text, "Initial field focus"
                        assert dialog.text.GetInsertionPoint() == 0, "Initial caret"
                        assert dialog.text.GetSelection() == (0, 0), "Initial selection"
                        assert not dialog.text.IsEditable()
                        assert dialog.text.GetValue() == label("msg_tags")
                        assert dialog.text.GetName() == label("title_tags")
                        assert dialog.close_button.GetLabel() == label("btn_close")
                        assert dialog.GetEscapeId() == wx.ID_CANCEL
                        assert dialog.text.GetFont().GetPointSize() == 16
                        assert dialog.text.GetBackgroundColour() == colour
                        dialog.text.SelectAll()
                        assert dialog.text.GetStringSelection() == label("msg_tags")
                        assert dialog.text.CanCopy()
                        dialog.text.SetInsertionPoint(0)
                        dialog.text.Navigate()
                        assert wx.Window.FindFocus() is dialog.close_button, "Forward Tab"
                        dialog.close_button.Navigate(flags=wx.NavigationKeyEvent.IsBackward)
                        assert wx.Window.FindFocus() is dialog.text, "Backward Tab"
                        checks.append((language, theme))
                    except Exception as exc:
                        failures.append(exc)
                    finally:
                        if theme == "light":
                            event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
                            event.SetKeyCode(wx.WXK_ESCAPE)
                            dialog.GetEventHandler().ProcessEvent(event)
                        else:
                            event = wx.CommandEvent(wx.EVT_BUTTON.typeId, wx.ID_CANCEL)
                            event.SetEventObject(dialog.close_button)
                            dialog.close_button.GetEventHandler().ProcessEvent(event)

                def force_close(dialog=dialog):
                    if dialog and dialog.IsModal():
                        failures.append(AssertionError("Close/Escape did not dismiss reader"))
                        dialog.EndModal(wx.ID_CANCEL)

                wx.CallLater(150, check)
                timeout = wx.CallLater(1500, force_close)
                try:
                    assert dialog.ShowModal() == wx.ID_CANCEL
                finally:
                    timeout.Stop()
                dialog.Destroy()
                application.Yield()
                assert wx.Window.FindFocus() is editor
    finally:
        parent.Destroy()
        application.Yield()
    assert not failures, failures
    assert checks == [(language, theme) for language in ("pl", "en") for theme in ("dark", "light")]
    print("Real wx tag help: read-only, complete PL/EN, theme/font, focus/Tab/close: OK")


if __name__ == "__main__":
    main()
