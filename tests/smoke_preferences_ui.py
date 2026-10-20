"""Real wx default/cancel command routing with synthetic preferences, no model."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch


def main():
    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG
    from omnisonic.shortcuts import default_shortcut_bindings, default_shortcut_enabled

    application = wx.App(False)
    results = []

    def route_dialog_command(dialog, key):
        command_id = dialog.GetAffirmativeId() if key == wx.WXK_RETURN else dialog.GetEscapeId()
        button = dialog.FindWindowById(command_id)
        assert button is not None
        event = wx.CommandEvent(wx.EVT_BUTTON.typeId, command_id)
        event.SetEventObject(button)
        button.GetEventHandler().ProcessEvent(event)

    def command_modal(dialog, control, key, expected, *, intermediate=None):
        errors = []
        timer = None
        watchdog = None

        def timed_out():
            errors.append(AssertionError("Dialog did not respond to its default/cancel command"))
            if dialog.IsModal():
                dialog.EndModal(wx.ID_CANCEL)

        def press():
            try:
                control.SetFocus()
                route_dialog_command(dialog, key)
                if intermediate is not None:
                    wx.CallLater(150, intermediate, dialog)
            except Exception as error:
                errors.append(error)
                if dialog.IsModal():
                    dialog.EndModal(wx.ID_CANCEL)

        try:
            timer = wx.CallLater(100, press)
            watchdog = wx.CallLater(3000, timed_out)
            result = dialog.ShowModal()
            if errors:
                raise errors[0]
            assert result == expected, (result, expected)
        finally:
            if timer is not None:
                timer.Stop()
            if watchdog is not None:
                watchdog.Stop()
            dialog.Destroy()
            application.Yield()

    try:
        for language in ("en", "pl"):

            def translator(key, language=language):
                return desktop.translate(desktop.LOCALE, language, key)

            for key, expected in ((wx.WXK_RETURN, wx.ID_OK), (wx.WXK_ESCAPE, wx.ID_CANCEL)):
                editor = desktop.PresetEditDialog(None, translator, "Synthetic", "Transcript")
                command_modal(editor, editor.name_ctrl, key, expected)

            cfg = deepcopy(DEFAULT_CONFIG)
            cfg["language"] = language
            for key, expected in ((wx.WXK_RETURN, wx.ID_OK), (wx.WXK_ESCAPE, wx.ID_CANCEL)):
                settings = desktop.SettingsDialog(None, current_cfg=cfg)
                with patch.object(wx, "MessageBox", return_value=wx.YES) as message:
                    command_modal(settings, settings.txt_pref_gen, key, expected)
                    message.assert_not_called()

            settings = desktop.SettingsDialog(None, current_cfg=cfg)
            settings.txt_pref_gen.SetValue("changed-prefix")
            intermediate_seen = []

            def after_decline(dialog, seen=intermediate_seen):
                seen.append(dialog.IsModal())
                # The first cancel command keeps this dialog; the second discards it.
                route_dialog_command(dialog, wx.WXK_ESCAPE)

            with patch.object(wx, "MessageBox", side_effect=[wx.NO, wx.YES]) as message:
                command_modal(
                    settings,
                    settings.txt_pref_gen,
                    wx.WXK_ESCAPE,
                    wx.ID_CANCEL,
                    intermediate=after_decline,
                )
                assert message.call_count == 2
            assert intermediate_seen == [True]
            assert cfg["prefix_gen"] == DEFAULT_CONFIG["prefix_gen"]

            settings = desktop.SettingsDialog(None, current_cfg=cfg)
            try:
                settings.shortcut_bindings["generate"] = "Ctrl+Shift+G"
                settings.shortcut_bindings["save_result"] = "Ctrl+Shift+G"
                with patch.object(wx, "MessageBox", return_value=wx.OK) as message:
                    assert not settings._save_shortcut_settings()
                    assert (
                        translator("shortcut_conflict").split("{", 1)[0]
                        in message.call_args.args[0]
                    )
                settings.shortcut_enabled["save_result"] = False
                settings.chk_shortcuts_enabled.SetValue(False)
                assert settings._save_shortcut_settings()
                assert not settings.cfg["shortcuts_enabled"]
                assert not settings.cfg["shortcut_enabled"]["save_result"]
                settings.OnRestoreShortcutDefaults(None)
                assert settings.shortcut_bindings == default_shortcut_bindings()
                assert settings.shortcut_enabled == default_shortcut_enabled()
                assert settings.chk_shortcuts_enabled.GetValue()
                settings.list_shortcuts.SetFocus()
                assert wx.Window.FindFocus() == settings.list_shortcuts
                assert settings.txt_shortcut.GetName() == translator("shortcut_value_label")
                for index in range(settings.list_shortcuts.GetCount()):
                    assert settings.list_shortcuts.GetString(index)
            finally:
                settings.Destroy()
                application.Yield()
            results.append(language)
    finally:
        application.Destroy()
    assert results == ["en", "pl"]
    print(
        "Preferences UI: PL/EN, default/cancel routing, discard, shortcut conflict/disable/default/focus: OK"
    )


if __name__ == "__main__":
    main()
