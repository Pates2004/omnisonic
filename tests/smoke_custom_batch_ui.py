"""Real custom-batch controls and WAV output with synthetic voice generation."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.materials import scratch_directory


def main():
    scratch = scratch_directory("custom-batch-wx-")
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import numpy as np
    import soundfile as sf
    import wx

    import omnisonic.app as desktop
    from omnisonic.batch import BatchResult
    from omnisonic.config import DEFAULT_CONFIG

    desktop.OmniVoiceGenerationConfig = SimpleNamespace
    desktop._ALL_LANGUAGES[:] = ["Auto", "English", "Polish"]

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

        def _CollectModelMemory(self):
            pass

    class Model:
        sampling_rate = 24000
        device = "cpu"
        _asr_pipe = None

        def __init__(self):
            self.calls = []
            self.started = threading.Event()
            self.proceed = threading.Event()
            self.proceed.set()

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            self.started.set()
            if not self.proceed.wait(20):
                raise TimeoutError("Owned synthetic batch model was not released")
            return [np.full(1200, 0.1, dtype=np.float32)]

    def select(control, identity):
        index = next(
            index for index in range(control.GetCount()) if control.GetClientData(index) == identity
        )
        control.SetSelection(index)

    application = wx.App(False)
    application.SetExitOnFrameDelete(False)
    reference = scratch / "reference.wav"
    sf.write(reference, np.zeros(800, dtype=np.float32), 16000)
    inputs = [scratch / "first.txt", scratch / "second.txt"]
    for index, path in enumerate(inputs):
        path.write_text(f"Synthetic sentence {index + 1}.", encoding="utf-8")
    desktop.PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("Alpha.pt", "Bravo.pt"):
        (desktop.PRESETS_DIR / name).write_bytes(b"Synthetic prompt, load mocked")

    for language in ("pl", "en"):
        frame = TestFrame(
            dict(
                DEFAULT_CONFIG,
                language=language,
                show_progress=False,
                auto_transcribe_reference=False,
                generated_audio_directory=str(scratch / language / "output"),
                unload_omnivoice_after_operation=False,
                unload_asr_after_transcription=False,
                warn_exit=False,
            ),
            None,
        )
        model = Model()
        frame.model = model
        frame._CheckVoiceInstruction = Mock(return_value=True)
        reference_prompt, preset_prompt = object(), object()
        frame._models.reference_prompt = Mock(return_value=reference_prompt)
        prompt_type = SimpleNamespace(load=Mock(return_value=preset_prompt))

        def idle(frame=frame):
            deadline = time.monotonic() + 25
            while frame.current_op is not None:
                application.Yield()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Custom batch GUI worker did not finish")
                time.sleep(0.005)
            application.Yield()

        def queue(frame=frame):
            frame.batch_items = [BatchResult(str(path)) for path in inputs]
            frame._refresh_batch_list()

        def run_batch(frame=frame, model=model, queue=queue, idle=idle):
            queue()
            before = len(model.calls)
            frame.OnGenBatch(None)
            idle()
            assert len(model.calls) == before + 2
            assert all(item.status == "done" for item in frame.batch_items)
            for item, source in zip(frame.batch_items, inputs, strict=True):
                result = Path(item.output)
                assert result.name == source.with_suffix(".wav").name
                info = sf.info(result)
                assert info.frames == 1200 and info.channels == 1 and info.samplerate == 24000
            return model.calls[before:]

        with (
            patch.object(wx, "MessageBox", return_value=wx.OK),
            patch.dict(sys.modules, {"omnivoice": SimpleNamespace(VoiceClonePrompt=prompt_type)}),
        ):
            try:
                application.SetTopWindow(frame)
                frame.notebook.SetSelection(frame.notebook.FindPage(frame.tab_batch))
                frame.Show()
                application.Yield()
                assert frame.batch_mode.GetSelection() == 3
                assert frame.batch_mode.GetString(3) == frame._("batch_custom")
                assert frame.batch_custom_voice.GetSelection() == 0
                assert frame.batch_custom_panel.IsShown()
                assert frame.batch_custom_language.GetValue() == "Auto"
                for control, label in (
                    (frame.batch_custom_voice, "batch_custom_voice"),
                    (frame.batch_custom_preset, "preset_list"),
                    (frame.batch_custom_audio, "ref_audio"),
                    (frame.batch_custom_text, "ref_text"),
                    (frame.batch_custom_language, "lang_select"),
                    (frame.batch_custom_instruction, "clone_instruct"),
                ):
                    assert control.GetName() == frame._(label)
                    assert not control.GetName().startswith("Untranslated")

                # Real native Tab navigation stays within the reference group.
                frame.batch_custom_preset.SetFocus()
                application.Yield()
                frame.batch_custom_preset.Navigate()
                assert wx.Window.FindFocus() is frame.btn_batch_preset_refresh
                frame.batch_custom_audio.SetFocus()
                application.Yield()
                frame.batch_custom_audio.Navigate()
                assert wx.Window.FindFocus() is frame.btn_batch_ref_browse

                select(frame.combo_presets, "Alpha.pt")
                select(frame.batch_custom_preset, "Bravo.pt")
                frame.cfg["preset_display_mode"] = "path"
                frame.RefreshPresets()
                assert (
                    frame.combo_presets.GetClientData(frame.combo_presets.GetSelection())
                    == "Alpha.pt"
                )
                assert (
                    frame.batch_custom_preset.GetClientData(
                        frame.batch_custom_preset.GetSelection()
                    )
                    == "Bravo.pt"
                )
                frame._UpdateBatchCustomControls()
                assert not frame.batch_custom_audio.IsEnabled()
                assert not frame.batch_custom_text.IsEnabled()
                assert not frame.btn_batch_ref_browse.IsEnabled()
                (desktop.PRESETS_DIR / "Bravo.pt").unlink()
                frame.RefreshPresets()
                assert frame.batch_custom_preset.GetSelection() == 0
                assert frame.batch_custom_audio.IsEnabled()
                assert (
                    frame.combo_presets.GetClientData(frame.combo_presets.GetSelection())
                    == "Alpha.pt"
                )
                (desktop.PRESETS_DIR / "Bravo.pt").write_bytes(b"Synthetic prompt, load mocked")
                frame.RefreshPresets()

                frame.clone_ref_audio.SetValue("unused-main-tab.wav")
                frame.clone_ref_text.SetValue("Must not be borrowed")
                frame.clone_lang.SetValue("Polish")
                frame.clone_instruct.SetValue("shout")
                frame.batch_custom_audio.SetValue(str(reference))
                frame.batch_custom_text.SetValue("Must be cleared")
                frame.batch_custom_audio.SetValue(f'"{reference}"')
                assert frame.batch_custom_text.GetValue() == ""
                assert frame.clone_ref_text.GetValue() == "Must not be borrowed"
                frame.batch_custom_text.SetValue("Independent reference")
                frame.batch_custom_language.SetValue("English")
                frame.batch_custom_instruction.SetValue("whisper")

                # Recording/pending data block the same ancestor without a real mic.
                for state in ("rec_stream", "rec_data"):
                    setattr(frame, state, object() if state == "rec_stream" else [b"Synthetic"])
                    frame._set_operation_controls_enabled(True)
                    frame.RefreshPresets()
                    frame._UpdateBatchCustomControls()
                    assert not frame.batch_custom_panel.IsEnabled()
                    for control in (
                        frame.batch_custom_voice,
                        frame.batch_custom_preset,
                        frame.batch_custom_audio,
                        frame.batch_custom_text,
                        frame.batch_custom_language,
                        frame.batch_custom_instruction,
                        frame.btn_batch_ref_browse,
                        frame.btn_batch_preset_refresh,
                    ):
                        assert not control.IsEnabled(), "Busy recording leaked a custom input"
                    setattr(frame, state, None if state == "rec_stream" else [])
                    frame._set_operation_controls_enabled(True)
                    assert frame.batch_custom_panel.IsEnabled()

                # An in-flight item owns a snapshot and blocks the custom panel.
                queue()
                model.started.clear()
                model.proceed.clear()
                before = len(model.calls)
                frame.OnGenBatch(None)
                assert model.started.wait(15), "Synthetic generation did not start"
                assert not frame.batch_custom_panel.IsEnabled()
                assert not frame.batch_custom_preset.IsEnabled()
                assert not frame.batch_mode.IsEnabled()
                frame.RefreshPresets()
                frame._UpdateBatchCustomControls()
                for control in (
                    frame.batch_custom_voice,
                    frame.batch_custom_preset,
                    frame.batch_custom_audio,
                    frame.batch_custom_text,
                    frame.batch_custom_language,
                    frame.batch_custom_instruction,
                    frame.btn_batch_ref_browse,
                    frame.btn_batch_preset_refresh,
                ):
                    assert not control.IsEnabled(), "Refreshing leaked an in-flight custom input"
                frame.batch_custom_language.SetValue("Polish")
                frame.batch_custom_instruction.SetValue("shout")
                model.proceed.set()
                idle()
                assert frame.batch_custom_panel.IsEnabled()
                assert frame.batch_mode.IsEnabled()
                assert all(call["language"] == "English" for call in model.calls[before:])
                assert all(call["instruct"] == "whisper" for call in model.calls[before:])
                frame._models.reference_prompt.assert_called_once()
                prompt_args = frame._models.reference_prompt.call_args.args
                assert prompt_args[2:] == (str(reference), "Independent reference")

                frame.batch_custom_language.SetValue("English")
                frame.batch_custom_instruction.SetValue("whisper")
                select(frame.batch_custom_preset, "Bravo.pt")
                frame._UpdateBatchCustomControls()
                calls = run_batch()
                assert all(call["voice_clone_prompt"] is preset_prompt for call in calls)
                prompt_type.load.assert_called_once_with(str(desktop.PRESETS_DIR / "Bravo.pt"))

                for voice in (1, 2):
                    frame.batch_custom_voice.SetSelection(voice)
                    frame.OnBatchCustomVoiceChanged(None)
                    assert not frame.batch_custom_reference_panel.IsShown()
                    assert frame.batch_custom_instruction_panel.IsShown() == (voice == 1)
                    calls = run_batch()
                    assert all("voice_clone_prompt" not in call for call in calls)
                    assert all(("instruct" in call) == (voice == 1) for call in calls)

                frame.batch_mode.SetSelection(2)
                frame.OnBatchModeChanged(None)
                assert not frame.batch_custom_panel.IsShown()
                frame.batch_mode.SetSelection(3)
                frame.OnBatchModeChanged(None)
                assert frame.batch_custom_panel.IsShown()
                print(
                    f"Real custom batch ({language}): presets, references, snapshot, WAV and Tab: OK"
                )
            finally:
                model.proceed.set()
                idle()
                frame._models.release_all()
                frame.Destroy()
                application.Yield()
    application.Destroy()


if __name__ == "__main__":
    main()
