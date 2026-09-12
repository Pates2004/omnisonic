"""Invisible wx tests for memory settings and lazy model use in all desktop modes."""

from __future__ import annotations

import gc
import os
import tempfile
import time
import weakref
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    scratch = Path(tempfile.mkdtemp(prefix="memory-ui-", dir=root / "trash"))
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import numpy as np
    import soundfile as sf
    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG, CONFIG_FILE, PRESETS_DIR, load_config
    from omnisonic.operations import OperationState, execute_worker
    from omnivoice.models.omnivoice import WhisperASR

    desktop.np = np
    desktop.OmniVoiceGenerationConfig = SimpleNamespace
    desktop.load_waveform = lambda path: sf.read(path, dtype="float32")
    loaded, pipelines = [], []
    mode = {"fail": False, "cancel": False}

    class Pipe:
        def __call__(self, *args, **kwargs):
            return {"text": "Test reference."}

    class Prompt:
        ref_text = "Test reference."

        def save(self, path):
            Path(path).write_text("synthetic UI preset", encoding="utf-8")

    class Transcriber(WhisperASR):
        def load_asr_model(self):
            self._asr_pipe = Pipe()
            pipelines.append(weakref.ref(self._asr_pipe))

        def unload_asr_model(self):
            self._asr_pipe = None

    class Model(Transcriber):
        sampling_rate = 22050

        def generate(self, **kwargs):
            if mode["fail"]:
                raise ValueError("Intentional GUI failure")
            if mode["cancel"]:
                frame.current_op.request_cancel()
            return [np.ones(1000, dtype=np.float32) * 0.1]

        def create_voice_clone_prompt(self, **kwargs):
            if not kwargs.get("ref_text"):
                if self._asr_pipe is None:
                    self.load_asr_model()
                self.transcribe(kwargs["ref_audio"])
                if self.unload_asr_after_transcription:
                    assert self._asr_pipe is None
            return Prompt()

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

        def _LoadModelWorker(self, state, settings):
            model = Model()
            loaded.append(weakref.ref(model))
            return model

        def _CreateTranscriber(self, settings):
            return Transcriber()

        def _CollectModelMemory(self):
            gc.collect()

    class SilentProgress:
        """Exercise RunOperation's modal branch without opening visible dialogs."""

        def __init__(self, parent, cfg, title, message, worker, *args):
            self.state = OperationState()
            self.worker, self.args = worker, args

        def ShowModal(self):
            return execute_worker(self.state, self.worker, *self.args)

    app = wx.App(False)
    frame = TestFrame(
        dict(DEFAULT_CONFIG, show_progress=False, auto_transcribe_reference=False), None
    )

    def idle():
        deadline = time.monotonic() + 30
        while frame.current_op is not None:
            app.Yield()
            if time.monotonic() > deadline:
                raise TimeoutError("Memory UI test timed out")
            time.sleep(0.01)
        app.Yield()
        gc.collect()

    def released():
        idle()
        assert frame.model is None
        assert all(ref() is None for ref in loaded + pipelines)
        assert frame.btn_toggle_model.GetLabel() == frame._("load_model")

    with (
        patch.object(wx, "MessageBox", return_value=wx.OK),
        patch.object(wx, "Bell"),
        patch.object(desktop, "OperationDialog", SilentProgress),
    ):
        try:
            dialog = desktop.SettingsDialog(frame, current_cfg=deepcopy(frame.cfg))
            try:
                assert not dialog.chk_unload_asr.GetValue()
                assert not dialog.chk_unload_omnivoice.GetValue()
                assert not dialog._has_unsaved_changes()
                dialog.chk_unload_asr.SetValue(True)
                dialog.chk_unload_omnivoice.SetValue(True)
                assert dialog._has_unsaved_changes()
                with patch.object(dialog, "EndModal"):
                    dialog.OnSave(None)
                desktop.SaveBasicConfig(dialog.cfg)
                saved = load_config(CONFIG_FILE)
                assert saved["unload_asr_after_transcription"]
                assert saved["unload_omnivoice_after_operation"]
                frame.cfg = saved
                with patch.object(wx, "MessageBox", return_value=wx.YES):
                    dialog.OnResetApp(None)
                assert not dialog.chk_unload_asr.GetValue()
                assert not dialog.chk_unload_omnivoice.GetValue()
            finally:
                dialog.Destroy()

            source = scratch / "reference.wav"
            sf.write(source, np.ones(1600) * 0.1, 16000)
            frame.clone_ref_audio.SetValue(str(source))
            for _ in range(2):
                frame.OnTranscribeReference(None)
                released()
                assert frame.clone_ref_text.GetValue() == "Test reference."
            assert not loaded, "ASR unnecessarily loaded OmniVoice"

            frame.cfg["auto_transcribe_reference"] = True
            frame.clone_ref_audio.SetValue(str(source))
            frame._MaybeAutoTranscribeReference()
            released()
            assert frame.clone_ref_text.GetValue() == "Test reference."
            assert not loaded
            frame.cfg["auto_transcribe_reference"] = False

            for progress in (False, True):
                frame.cfg["show_progress"] = progress
                for handler, control in (
                    (frame.OnGenAuto, frame.auto_text),
                    (frame.OnGenDesign, frame.design_text),
                    (frame.OnGenClone, frame.clone_text),
                ):
                    control.SetValue("Test sentence.")
                    handler(None)
                    released()
                    assert frame.audio_data.size == 1000
                    assert frame.sample_rate == 22050
                    assert frame.btn_play.IsEnabled() and frame.btn_save.IsEnabled()

            frame.cfg["show_progress"] = False
            frame._StartPresetRebuild(str(source), None, PRESETS_DIR / "test.pt")
            released()
            assert (PRESETS_DIR / "test.pt").is_file()
            first, second = scratch / "one.txt", scratch / "two.txt"
            first.write_text("First sentence.", encoding="utf-8")
            second.write_text("Second sentence.", encoding="utf-8")
            frame._scan_batch_inputs([str(first), str(second)])
            idle()
            frame.batch_mode.SetSelection(2)
            frame.batch_output.SetValue(str(scratch / "batch-output"))
            before = len(loaded)
            frame.OnGenBatch(None)
            released()
            assert len(loaded) == before + 1
            assert all(item.status == "done" for item in frame.batch_items)

            for action in ("fail", "cancel"):
                mode[action] = True
                frame.OnGenAuto(None)
                released()
                mode[action] = False
                frame.OnGenAuto(None)
                released()
                assert frame.audio_data.size == 1000

            # The normal manual Load/Unload button still works with both new
            # settings off, and OperationState never retains the loaded model.
            frame.cfg["unload_asr_after_transcription"] = False
            frame.cfg["unload_omnivoice_after_operation"] = False
            frame.OnToggleModel(None)
            idle()
            assert frame.model is not None
            frame.OnToggleModel(None)
            released()
            print(
                "Memory settings, persistence/reset, all generation modes, preset, batch, ASR reload, error/cancel: OK"
            )
        finally:
            idle()
            if frame._reference_timer:
                frame._reference_timer.Stop()
            frame.Destroy()
            app.Yield()
            app.Destroy()


if __name__ == "__main__":
    main()
