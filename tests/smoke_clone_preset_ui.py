"""Exercise actual wx preset controls with an isolated profile and fake inference."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import Mock, patch

from tests.materials import scratch_directory


def main():
    scratch = scratch_directory("clone-preset-wx-")
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG
    from omnisonic.operations import OperationState

    calls = []

    class Prompt:
        def __init__(self, text):
            self.ref_text = text

        def save(self, path):
            Path(path).write_text(json.dumps({"text": self.ref_text}), encoding="utf-8")

    class Model:
        sampling_rate = 24000
        _asr_pipe = None

        def create_voice_clone_prompt(self, **kwargs):
            calls.append(kwargs)
            return Prompt(kwargs["ref_text"] or "Synthetic ASR transcript")

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

        def _CollectModelMemory(self):
            pass

    application = wx.App(False)

    def pump(frame):
        deadline = time.monotonic() + 10
        while frame.current_op is not None:
            application.Yield()
            if time.monotonic() > deadline:
                raise TimeoutError("Synthetic preset save did not finish")
            time.sleep(0.005)
        application.Yield()

    def click(button):
        event = wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId())
        event.SetEventObject(button)
        button.GetEventHandler().ProcessEvent(event)

    def delete(control, *, shift=False):
        event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
        event.SetKeyCode(wx.WXK_DELETE)
        event.SetShiftDown(shift)
        control.GetEventHandler().ProcessEvent(event)

    def select(control, filename):
        index = next(
            index for index in range(control.GetCount()) if control.GetClientData(index) == filename
        )
        control.SetSelection(index)

    real_name_dialog = wx.TextEntryDialog
    names, warnings = [], []
    next_name = ""
    warning_answer = wx.ID_YES

    def name_dialog(parent, message, title):
        assert parent is frame
        assert message == frame._("prompt_preset_name")
        assert title == frame._("preset_name_title")
        dialog = real_name_dialog(parent, message, title)
        dialog.SetValue(next_name)
        names.append(next_name)
        wx.CallLater(30, dialog.EndModal, wx.ID_OK)
        return dialog

    def warning_dialog(parent, message, title, style):
        assert parent is frame
        assert title == frame._("warning_title")
        dialog = Mock()
        warnings.append(message)
        dialog.ShowModal.return_value = warning_answer
        dialog.IsCheckBoxChecked.return_value = False
        return dialog

    try:
        for language in ("pl", "en"):
            frame = TestFrame(
                dict(
                    DEFAULT_CONFIG,
                    language=language,
                    show_progress=False,
                    warn_exit=False,
                    auto_transcribe_reference=False,
                    clean_temp=False,
                ),
                None,
            )
            try:
                frame._autoload_timer.Stop()
                frame.model = Model()
                reference = scratch / f"{language}-reference.wav"
                reference.write_bytes(b"Synthetic audio; encoding is mocked")
                frame.clone_ref_audio.SetValue(str(reference))
                frame.clone_ref_text.SetValue("Synthetic reference transcript.")
                assert frame.btn_save_preset.GetParent() is frame.tab_clone
                assert frame.btn_save_preset.GetName() == frame._("btn_save_preset_clone")
                assert frame.combo_presets.GetName() == frame._("preset_list")
                assert not hasattr(frame, "preset_source_audio")
                assert not hasattr(frame, "preset_source_ref_text")
                for control in (
                    frame.list_presets,
                    frame.btn_edit_preset,
                    frame.btn_del_preset_manager,
                    frame.btn_del_all_presets_manager,
                ):
                    assert control.GetParent() is frame.tab_presets
                clone_children = frame.tab_clone.GetChildren()
                assert (
                    clone_children.index(frame.clone_ref_text)
                    < clone_children.index(frame.btn_save_preset)
                    < clone_children.index(frame.clone_instruct)
                )

                with (
                    patch.object(wx, "TextEntryDialog", side_effect=name_dialog),
                    patch.object(wx, "RichMessageDialog", side_effect=warning_dialog),
                    patch.object(wx, "MessageBox", return_value=wx.OK) as messages,
                    patch.object(wx, "Bell"),
                ):
                    next_name = f"{language}-Alpha"
                    click(frame.btn_save_preset)
                    pump(frame)
                    alpha = desktop.PRESETS_DIR / f"{next_name}.pt"
                    assert alpha.is_file()
                    assert calls[-1]["ref_audio"] == str(reference)
                    assert calls[-1]["ref_text"] == "Synthetic reference transcript."

                    # Menu/accelerator routing saves the same current clone reference.
                    next_name = f"{language}-Bravo"
                    frame.notebook.SetSelection(1)
                    event = wx.CommandEvent(wx.EVT_MENU.typeId, frame.item_save_preset.GetId())
                    frame.GetEventHandler().ProcessEvent(event)
                    pump(frame)
                    bravo = desktop.PRESETS_DIR / f"{next_name}.pt"
                    assert bravo.is_file() and frame.notebook.GetCurrentPage() is frame.tab_clone
                    select(frame.list_presets, alpha.name)
                    select(frame.combo_presets, bravo.name)
                    warning_answer = wx.ID_NO
                    delete(frame.combo_presets)
                    assert alpha.exists() and bravo.exists()
                    warning_answer = wx.ID_YES
                    delete(frame.combo_presets)
                    assert alpha.exists() and not bravo.exists()
                    assert frame.combo_presets.GetSelection() == 0
                    assert frame.list_presets.GetClientData(0) == alpha.name
                    warning_count = len(warnings)
                    delete(frame.combo_presets)
                    delete(frame.combo_presets, shift=True)
                    assert alpha.exists() and len(warnings) == warning_count

                    # Disabled controls and direct stale callbacks cannot mutate presets.
                    select(frame.combo_presets, alpha.name)
                    for name, value in (
                        ("current_op", OperationState()),
                        ("rec_stream", Mock()),
                        ("rec_data", [b"Synthetic pending microphone take"]),
                    ):
                        setattr(frame, name, value)
                        frame._set_operation_controls_enabled(name != "current_op")
                        assert not frame.combo_presets.IsEnabled()
                        assert not frame.btn_save_preset.IsEnabled()
                        count = len(names)
                        frame.OnClonePresetKeyDown(
                            Mock(GetKeyCode=lambda: wx.WXK_DELETE, ShiftDown=lambda: True)
                        )
                        frame.OnSavePresetPrompt(None)
                        assert alpha.exists() and len(names) == count
                        setattr(frame, name, [] if name == "rec_data" else None)
                        frame._set_operation_controls_enabled(True)
                    assert frame.combo_presets.IsEnabled() and frame.btn_save_preset.IsEnabled()

                    delete(frame.combo_presets, shift=True)
                    assert not alpha.exists() and len(warnings) == warning_count
                    assert frame.combo_presets.GetCount() == 1 and not frame.list_presets.GetCount()
                    next_name = f"{language}-Manager"
                    click(frame.btn_save_preset)
                    pump(frame)
                    manager = desktop.PRESETS_DIR / f"{next_name}.pt"
                    select(frame.list_presets, manager.name)
                    delete(frame.list_presets, shift=True)
                    assert not manager.exists() and frame.combo_presets.GetCount() == 1
                    assert reference.is_file()
                    messages.assert_not_called()
            finally:
                if frame.current_op is not None:
                    pump(frame)
                for name in ("_autoload_timer", "_reference_timer", "play_timer", "prog_timer"):
                    timer = getattr(frame, name, None)
                    if timer is not None:
                        timer.Stop()
                frame.Destroy()
                application.Yield()
    finally:
        application.Destroy()
    print("Clone save button/shortcut and selected Delete/Shift+Delete, PL/EN, busy safety: OK")
    print(f"Synthetic fixtures: {scratch}")


if __name__ == "__main__":
    main()
