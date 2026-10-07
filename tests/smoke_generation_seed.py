"""Real wx seed wiring with synthetic RNG samples, not neural voice generation."""

from __future__ import annotations

import os
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    (root / "trash").mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="generation-seed-ui-", dir=root / "trash"))
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import numpy as np
    import soundfile as sf
    import torch
    import wx

    import omnisonic.app as desktop
    from omnisonic.batch import BatchResult
    from omnisonic.config import DEFAULT_CONFIG
    from omnivoice import VoiceClonePrompt

    desktop.np = np
    desktop.OmniVoiceGenerationConfig = SimpleNamespace
    calls = []

    def synthetic_samples():
        return (np.random.random(32).astype(np.float32) + torch.rand(32).numpy()) * 0.1

    class Model:
        device = "cpu"
        sampling_rate = 24000
        _asr_pipe = None

        def generate(self, **kwargs):
            samples = synthetic_samples()
            calls.append(samples.copy())
            return [samples]

        def create_voice_clone_prompt(self, ref_text=None, **kwargs):
            return VoiceClonePrompt(
                torch.zeros((2, 4), dtype=torch.int64), ref_text or "Reference", 0.1
            )

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

    application = wx.App(False)
    frame = TestFrame(
        dict(
            DEFAULT_CONFIG,
            show_progress=False,
            auto_save_gen=False,
            auto_transcribe_reference=False,
        ),
        None,
    )
    application.SetTopWindow(frame)
    frame.model = Model()

    def idle():
        deadline = time.monotonic() + 30
        while frame.current_op is not None:
            application.Yield()
            if time.monotonic() > deadline:
                raise TimeoutError("Synthetic seed operation did not finish")
            time.sleep(0.01)
        application.Yield()

    def set_enabled(value):
        frame.chk_seed.SetValue(value)
        event = wx.CommandEvent(wx.EVT_CHECKBOX.typeId, frame.chk_seed.GetId())
        event.SetEventObject(frame.chk_seed)
        frame.chk_seed.GetEventHandler().ProcessEvent(event)
        assert frame.spin_seed.IsEnabled() == value

    try:
        with patch.object(wx, "MessageBox", return_value=wx.OK), patch.object(wx, "Bell"):
            for remember in (False, True):
                panel = desktop.scrolled.ScrolledPanel(frame)
                preferences = SimpleNamespace(
                    cfg=dict(
                        DEFAULT_CONFIG,
                        remember_ai_settings=remember,
                        use_fixed_seed=True,
                        ai_seed=42,
                    ),
                    _=frame._,
                )
                desktop.OmniVoiceFrame.SetupAdvTab(preferences, panel)
                assert preferences.chk_seed.GetValue() == remember
                assert preferences.spin_seed.GetValue() == (42 if remember else 0)
                assert preferences.spin_seed.IsEnabled() == remember
                assert preferences.chk_seed.GetName() == frame._("use_fixed_seed")
                assert preferences.spin_seed.GetName() == frame._("seed_value")
                panel.Destroy()
            reference = scratch / "reference.wav"
            sf.write(reference, np.zeros(64, dtype=np.float32), 24000)
            frame.clone_ref_audio.SetValue(str(reference))
            frame.clone_ref_text.SetValue("Synthetic reference")
            for name in ("clone", "auto", "design"):
                getattr(frame, name + "_text").SetValue("Synthetic text")
            assert not frame.chk_seed.GetValue() and not frame.spin_seed.IsEnabled()
            set_enabled(True)
            for seed in (0, 42, 2147483647):
                frame.spin_seed.SetValue(seed)
                for action in (frame.OnGenClone, frame.OnGenAuto, frame.OnGenDesign):
                    before = len(calls)
                    action(None)
                    idle()
                    action(None)
                    idle()
                    assert len(calls) == before + 2
                    np.testing.assert_array_equal(calls[-1], calls[-2])
                    assert frame.btn_save.IsEnabled()

            source = scratch / "input.txt"
            source.write_text("Synthetic batch text", encoding="utf-8")
            frame.batch_output.SetValue(str(scratch / "output"))
            for mode in range(3):
                frame.batch_mode.SetSelection(mode)
                before = len(calls)
                for _ in range(2):
                    frame.batch_items = [BatchResult(str(source))]
                    frame.batch_list.DeleteAllItems()
                    frame.batch_list.InsertItem(0, source.name)
                    frame.OnGenBatch(None)
                    idle()
                    assert frame.batch_items[0].status == "done"
                    assert sf.info(frame.batch_items[0].output).frames == 32
                assert len(calls) == before + 2
                np.testing.assert_array_equal(calls[-1], calls[-2])

            set_enabled(False)
            np.random.seed(1234)
            torch.default_generator.manual_seed(1234)
            expected = [synthetic_samples(), synthetic_samples()]
            np.random.seed(1234)
            torch.default_generator.manual_seed(1234)
            for samples in expected:
                frame.OnGenAuto(None)
                idle()
                np.testing.assert_array_equal(calls[-1], samples)

            set_enabled(True)
            frame.spin_seed.SetValue(42)
            settings = desktop.SettingsDialog(frame, current_cfg=deepcopy(frame.cfg))
            try:
                with patch.object(wx, "MessageBox", return_value=wx.YES):
                    settings.OnResetAI(None)
                assert not frame.chk_seed.GetValue() and frame.spin_seed.GetValue() == 0
                assert not frame.spin_seed.IsEnabled()
                settings._restore_parent_ai_state()
                assert frame.chk_seed.GetValue() and frame.spin_seed.GetValue() == 42
                assert frame.spin_seed.IsEnabled()
            finally:
                settings.Destroy()
            print(
                "Seed UI: clone/design/auto, all batch modes, zero/max, disable and reset rollback: OK"
            )
    finally:
        idle()
        frame.prog_timer.Stop()
        if frame._reference_timer:
            frame._reference_timer.Stop()
        if frame._autoload_timer:
            frame._autoload_timer.Stop()
        frame.Destroy()
        application.Yield()
        application.Destroy()
    print(f"Synthetic seed fixtures: {scratch}")


if __name__ == "__main__":
    main()
