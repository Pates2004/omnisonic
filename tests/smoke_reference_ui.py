"""Invisible wx integration test for reference selection, settings and stale ASR results."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    (root / "trash").mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="reference-ui-", dir=root / "trash"))
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import numpy as np
    import soundfile as sf
    import wx

    import omnisonic.app as desktop
    from omnisonic.config import CONFIG_FILE, DEFAULT_CONFIG, load_config
    from omnisonic.operations import OperationState

    desktop.OmniVoiceGenerationConfig = SimpleNamespace
    desktop.load_waveform = lambda path: sf.read(path, dtype="float32")

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

    class Model:
        _asr_pipe = None
        calls = 0
        fail = False

        def __init__(self):
            self.started = threading.Event()
            self.release = threading.Event()
            self.release.set()

        def load_asr_model(self):
            self._asr_pipe = True

        def transcribe(self, audio):
            self.calls += 1
            self.started.set()
            if not self.release.wait(15):
                raise TimeoutError("ASR test worker was not released")
            if self.fail:
                raise ValueError("Simulated ASR failure")
            return "First transcript" if float(audio[0][0]) < 0.5 else "Second transcript"

    app = wx.App(False)
    frame = TestFrame(dict(DEFAULT_CONFIG, show_progress=False), None)
    model = Model()
    frame.model = model

    def pump_until(condition, timeout=15):
        deadline = time.monotonic() + timeout
        while not condition():
            app.Yield()
            if time.monotonic() >= deadline:
                raise TimeoutError("Reference UI test did not finish")
            time.sleep(0.01)
        app.Yield()

    def idle():
        pump_until(lambda: frame.current_op is None)

    def select(path):
        frame.clone_ref_audio.SetValue(str(path))
        frame._MaybeAutoTranscribeReference()

    with patch.object(wx, "MessageBox", return_value=wx.OK):
        try:
            first, second = scratch / "first.wav", scratch / "second.wav"
            sf.write(first, np.full(800, 0.2), 16000)
            sf.write(second, np.full(800, 0.8), 16000)
            select(first)
            idle()
            assert frame.clone_ref_text.GetValue() == "First transcript"

            frame.cfg["auto_transcribe_reference"] = False
            count = model.calls
            select(second)
            assert model.calls == count and frame.clone_ref_text.GetValue() == ""
            frame.OnTranscribeReference(None)
            idle()
            assert frame.clone_ref_text.GetValue() == "Second transcript"

            frame.cfg["auto_transcribe_reference"] = True
            model.started.clear()
            model.release.clear()
            select(first)
            pump_until(model.started.is_set)
            select(second)
            model.release.set()
            pump_until(lambda: frame.clone_ref_text.GetValue() == "Second transcript")
            idle()

            model.started.clear()
            model.release.clear()
            select(first)
            pump_until(model.started.is_set)
            frame.clone_ref_text.SetValue("Manual correction")
            model.release.set()
            idle()
            assert frame.clone_ref_text.GetValue() == "Manual correction"

            frame.model = None
            select(second)
            assert frame._auto_reference_pending and frame.current_op is None
            frame.model = model
            state = OperationState()
            state.finished_event.set()
            frame._complete_operation(state, None)
            pump_until(lambda: frame.clone_ref_text.GetValue() == "Second transcript")
            idle()

            model.fail = True
            select(first)
            idle()
            count = model.calls
            frame._MaybeAutoTranscribeReference()
            assert model.calls == count and not frame._auto_reference_pending
            assert frame.clone_ref_text.GetValue() == ""
            model.fail = False

            model.started.clear()
            model.release.clear()
            select(first)
            pump_until(model.started.is_set)
            frame.current_op.request_cancel()
            model.release.set()
            idle()
            assert frame.clone_ref_text.GetValue() == "" and not frame._auto_reference_pending

            dialog = desktop.SettingsDialog(frame, current_cfg=deepcopy(frame.cfg))
            try:
                assert dialog.chk_auto_transcribe.GetValue()
                assert not dialog._has_unsaved_changes()
                dialog.chk_auto_transcribe.SetValue(False)
                assert dialog._has_unsaved_changes()
                with patch.object(dialog, "EndModal"):
                    dialog.OnSave(None)
                assert not dialog.cfg["auto_transcribe_reference"]
                desktop.SaveBasicConfig(dialog.cfg)
                assert CONFIG_FILE == scratch / "program/config/settings.json"
                assert not load_config(CONFIG_FILE)["auto_transcribe_reference"]
            finally:
                dialog.Destroy()
            editor = desktop.PresetEditDialog(frame, frame._, "test", "Old transcript.")
            try:
                editor.source_ctrl.SetValue(str(scratch / "different.wav"))
                assert editor.ref_text_ctrl.GetValue() == ""
                editor.ref_text_ctrl.SetValue("New transcript.")
                assert editor.ref_text_ctrl.GetValue() == "New transcript."
                editor.source_ctrl.SetValue("")
                assert editor.ref_text_ctrl.GetValue() == "Old transcript."
            finally:
                editor.Destroy()
            print(
                "Reference auto/manual ASR, stale results, edits, errors, cancellation and portable settings: OK"
            )
        finally:
            model.release.set()
            idle()
            if frame._reference_timer:
                frame._reference_timer.Stop()
            frame.Destroy()
            app.Yield()
            app.Destroy()


if __name__ == "__main__":
    main()
