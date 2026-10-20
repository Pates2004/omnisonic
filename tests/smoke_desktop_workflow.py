"""One coherent real-wx workflow with fake inference and mocked audio devices."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.materials import scratch_directory


def main():
    scratch = scratch_directory("desktop-workflow-")
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import numpy as np
    import soundfile as sf
    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG
    from omnivoice.utils.voice_design import resolve_instruct
    from tests.test_prompt_cache import Prompt as BasePrompt, Tokens

    desktop.np, desktop.sf, desktop.sd = np, sf, Mock()
    desktop.resolve_voice_instruction = resolve_instruct
    desktop.OmniVoiceGenerationConfig = SimpleNamespace
    desktop.load_waveform = lambda path: sf.read(path, dtype="float32")
    loads, generations = [], []

    class Prompt(BasePrompt):
        def save(self, path):
            Path(path).write_text(json.dumps({"text": self.ref_text}), encoding="utf-8")

        @classmethod
        def load(cls, path):
            return cls(Tokens([1, 2], "cpu"), json.loads(Path(path).read_text())["text"], 0.1)

    desktop.VoiceClonePrompt = Prompt

    class Model:
        sampling_rate = 24000
        device = "cpu"
        _asr_pipe = None

        def generate(self, **kwargs):
            resolve_instruct(kwargs.get("instruct"))
            generations.append(kwargs)
            return [np.full(2400, 0.1, dtype=np.float32)]

        def create_voice_clone_prompt(self, **kwargs):
            return Prompt(Tokens([1, 2], "cpu"), kwargs.get("ref_text") or "Reference.", 0.1)

    class TestFrame(desktop.OmniVoiceFrame):
        def ApplyConsoleState(self):
            pass

        def _LoadModelWorker(self, state, settings):
            model = Model()
            loads.append(model)
            return model

        def _CollectModelMemory(self):
            pass

    application = wx.App(False)
    frame = TestFrame(
        dict(
            DEFAULT_CONFIG,
            language="pl",
            show_progress=False,
            warn_exit=False,
            remember_ai_settings=False,
            auto_transcribe_reference=False,
            clean_temp=False,
            generated_audio_directory=str(scratch / "output"),
            recorded_audio_directory=str(scratch / "recordings"),
        ),
        None,
    )

    def pump(seconds=0):
        deadline = time.monotonic() + max(seconds, 0.01)
        while time.monotonic() < deadline or frame.current_op is not None:
            application.Yield()
            if time.monotonic() > deadline + 10:
                raise TimeoutError("Synthetic desktop operation did not finish")
            time.sleep(0.005)
        application.Yield()

    try:
        with (
            patch.object(wx, "MessageBox", return_value=wx.OK) as messages,
            patch.object(wx, "Bell"),
        ):
            # Explicit load/unload overrides a pending startup attempt.
            frame._autoload_timer.Stop()
            frame._autoload_timer = wx.CallLater(100, frame.AutoLoadModel)
            frame.OnToggleModel(None)
            pump()
            frame.OnToggleModel(None)
            pump(0.2)
            assert frame.model is None and len(loads) == 1
            frame.OnToggleModel(None)
            pump()
            reference = scratch / "reference.wav"
            sf.write(reference, np.zeros(1600, dtype=np.float32), 16000)
            frame.clone_ref_audio.SetValue(str(reference))
            frame.clone_ref_text.SetValue("Synthetic reference.")
            frame.clone_text.SetValue("Synthetic clone text.")
            frame.design_text.SetValue("Synthetic design text.")
            frame.auto_text.SetValue("Synthetic automatic text.")
            frame.OnGenAuto(None)
            pump()
            previous_audio = frame.audio_data
            for action, control in (
                (frame.OnGenClone, frame.clone_instruct),
                (frame.OnGenDesign, frame.design_custom_instruct),
            ):
                before = len(generations)
                control.SetValue("calm narrator")
                action(None)
                assert len(generations) == before and frame.audio_data is previous_audio
                assert frame._("voice_attributes_help_title") in messages.call_args.args[0]
                control.SetValue("whisper")
                action(None)
                pump()
                assert len(generations) == before + 1
                previous_audio = frame.audio_data

            # Create/edit/delete through the real handlers and synthetic files.
            with patch.object(wx, "TextEntryDialog") as name_dialog:
                name_dialog.return_value.ShowModal.return_value = wx.ID_OK
                name_dialog.return_value.GetValue.return_value = "First voice"
                frame.OnSavePresetPrompt(None)
                pump()
            assert (desktop.PRESETS_DIR / "First voice.pt").is_file()
            frame.list_presets.SetSelection(0)
            editor = Mock()
            editor.ShowModal.return_value = wx.ID_OK
            editor.name_ctrl.GetValue.return_value = "Edited voice"
            editor.source_ctrl.GetValue.return_value = ""
            editor.ref_text_ctrl.GetValue.return_value = "Updated reference."
            with patch.object(desktop, "PresetEditDialog", return_value=editor):
                frame.OnEditPreset(None)
                pump()
            preset = desktop.PRESETS_DIR / "Edited voice.pt"
            assert preset.is_file() and not (desktop.PRESETS_DIR / "First voice.pt").exists()
            with patch.object(wx, "RichMessageDialog") as warning:
                warning.return_value.IsCheckBoxChecked.return_value = False
                warning.return_value.ShowModal.return_value = wx.ID_NO
                frame.OnDelPreset(None)
                assert preset.exists()
                warning.return_value.ShowModal.return_value = wx.ID_YES
                frame.OnDelPreset(None)
            assert not preset.exists() and frame.combo_presets.GetCount() == 1
            for name in ("One", "Two"):
                Prompt(Tokens([1, 2], "cpu"), name, 0.1).save(desktop.PRESETS_DIR / f"{name}.pt")
            frame.RefreshPresets()
            with patch.object(wx, "RichMessageDialog") as warning:
                warning.return_value.IsCheckBoxChecked.return_value = False
                warning.return_value.ShowModal.return_value = wx.ID_NO
                frame.OnDelAllPresets(None)
                assert len(list(desktop.PRESETS_DIR.glob("*.pt"))) == 2
                warning.return_value.ShowModal.return_value = wx.ID_YES
                frame.OnDelAllPresets(None)
            assert not list(desktop.PRESETS_DIR.glob("*.pt"))

            # A failed microphone save can be explicitly discarded without exit/save.
            stream = Mock(samplerate=44100)
            desktop.sd.InputStream.return_value = stream
            frame.OnShortcutRecord(None)
            callback = desktop.sd.InputStream.call_args.kwargs["callback"]
            callback(np.full((441, 1), 0.25, dtype=np.float32), 441, None, None)
            assert frame.item_discard_recording.IsEnabled()
            assert not frame.btn_gen_clone.IsEnabled()
            with patch.object(
                desktop, "atomic_write", side_effect=PermissionError("Synthetic disk error")
            ):
                frame.OnShortcutRecord(None)
            assert frame.rec_stream is None and frame.rec_data
            previous_audio = frame.audio_data
            frame.OnGenAuto(None)  # A queued button command must preserve the prior result.
            assert frame.audio_data is previous_audio
            source_before_discard = frame.clone_ref_audio.GetValue()
            with patch.object(wx, "MessageDialog") as warning:
                warning.return_value.ShowModal.return_value = wx.ID_NO
                frame.OnDiscardRecording(None)
                assert frame.rec_data and not frame.btn_gen_auto.IsEnabled()
                warning.return_value.ShowModal.return_value = wx.ID_YES
                frame.OnDiscardRecording(None)
            assert not frame.rec_data and frame.btn_gen_auto.IsEnabled()
            assert not frame.item_discard_recording.IsEnabled()
            assert frame.clone_ref_audio.GetValue() == source_before_discard and reference.is_file()

            original_modal = desktop.SettingsDialog.ShowModal

            def lazy_settings(dialog):
                dialog.chk_unload_omnivoice.SetValue(True)
                wx.CallLater(50, dialog.OnSave, None)
                return original_modal(dialog)

            with patch.object(desktop.SettingsDialog, "ShowModal", lazy_settings):
                frame.OnOpenSettings(None)
            frame.design_combos[0].SetSelection(2)  # Female + repeated identical custom tag.
            frame.design_custom_instruct.SetValue("female, whisper")
            for action in (frame.OnGenDesign, frame.OnGenAuto):
                action(None)
                pump()
                assert frame.model is None and frame.audio_data is not None
                assert frame.btn_play.IsEnabled() and frame.btn_save.IsEnabled()

            destination = scratch / "saved-result.wav"
            with patch.object(wx, "FileDialog") as picker:
                dialog = picker.return_value.__enter__.return_value
                dialog.ShowModal.return_value = wx.ID_OK
                dialog.GetPath.return_value = str(destination)
                frame.OnSaveAudio(None)
            assert sf.info(destination).frames == 2400
            frame.OnShowVoiceAttributes(None)
            assert (
                "female" in messages.call_args.args[0] and "whisper" in messages.call_args.args[0]
            )
    finally:
        if frame.current_op is not None:
            pump()
        for name in ("_autoload_timer", "_reference_timer", "play_timer"):
            timer = getattr(frame, name, None)
            if timer is not None:
                timer.Stop()
        frame.prog_timer.Stop()
        frame.Destroy()
        application.Yield()
        application.Destroy()
    print(
        "Desktop workflow: explicit model intent, valid/rejected tags, preset lifecycle, recording discard, lazy generation and WAV save: OK"
    )
    print(f"Synthetic fixtures: {scratch}")


if __name__ == "__main__":
    main()
