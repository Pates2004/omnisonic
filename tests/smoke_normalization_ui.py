"""Invisible wx normalization flow with a real converter and synthetic synthesis."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[1]
    (root / "trash").mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="normalization-ui-", dir=root / "trash"))
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import numpy as np
    import soundfile as sf
    import wx

    import omnisonic.app as desktop
    from omnisonic.batch import BatchResult
    from omnisonic.config import DEFAULT_CONFIG
    from omnivoice.utils.text import normalize_text
    from tests.test_prompt_cache import Prompt, Tokens

    desktop.np = np
    desktop.OmniVoiceGenerationConfig = SimpleNamespace
    desktop._ALL_LANGUAGES[:] = ["Auto", "Polish", "English", "Tibetan"]
    calls = []

    class Model:
        _asr_pipe = None
        sampling_rate = 24000
        device = "cpu"

        def generate(self, text, language, normalize_text=False, **kwargs):
            assert normalize_text
            converted = convert(text, language=language)
            calls.append((language, converted))
            return [np.zeros(2400, dtype=np.float32)]

        def create_voice_clone_prompt(self, **kwargs):
            return Prompt(Tokens([1, 2], "cpu"), kwargs.get("ref_text") or "Reference.", 0.1)

    convert = normalize_text

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

    app = wx.App(False)
    frame = TestFrame(
        dict(
            DEFAULT_CONFIG,
            normalize_text=True,
            show_progress=False,
            auto_save_gen=False,
            auto_transcribe_reference=False,
        ),
        None,
    )
    frame.model = Model()

    def idle():
        deadline = time.monotonic() + 30
        while frame.current_op is not None:
            app.Yield()
            if time.monotonic() > deadline:
                raise TimeoutError("Normalization operation did not finish")
            time.sleep(0.01)
        app.Yield()

    with patch.object(wx, "MessageBox", return_value=wx.OK) as messages, patch.object(wx, "Bell"):
        try:
            reference = scratch / "reference.wav"
            sf.write(reference, np.zeros(2400), 24000)
            frame.clone_ref_audio.SetValue(str(reference))
            frame.clone_ref_text.SetValue("Synthetic reference.")
            frame.batch_output.SetValue(str(scratch / "results"))
            source = scratch / "input.txt"
            source.write_text("Mam 12 jabłek [laughter].", encoding="utf-8")
            for locale in ("pl", "en"):
                frame.cfg["language"] = locale
                for mode, control, language in (
                    (frame.OnGenClone, frame.clone_text, frame.clone_lang),
                    (frame.OnGenDesign, frame.design_text, frame.design_lang),
                    (frame.OnGenAuto, frame.auto_text, frame.auto_lang),
                ):
                    control.SetValue("Mam 12 jabłek [laughter].")
                    language.SetValue("Auto")
                    before = len(calls)
                    previous = frame.audio_data
                    mode(None)
                    assert len(calls) == before and frame.audio_data is previous
                    assert messages.call_args.args[0] == frame._("normalization_choose_language")
                    language.SetValue("Polish")
                    mode(None)
                    idle()
                    assert len(calls) == before + 1
                    assert calls[-1] == ("Polish", "Mam dwanaście jabłek [laughter].")
                    assert frame.audio_data is not None and frame.btn_save.IsEnabled()

                frame.auto_lang.SetValue("Tibetan")
                before = len(calls)
                frame.OnGenAuto(None)
                assert len(calls) == before
                assert messages.call_args.args[0] == frame._(
                    "normalization_unsupported_language"
                ).format(language="bo")
                frame.auto_lang.SetValue("English")
                frame.auto_text.SetValue("I have 12 apples [B EY1 S].")
                frame.OnGenAuto(None)
                idle()
                assert calls[-1] == ("English", "I have twelve apples [B EY1 S].")

                for mode in range(3):
                    frame.batch_items = [BatchResult(str(source))]
                    frame.batch_list.DeleteAllItems()
                    frame.batch_list.InsertItem(0, source.name)
                    frame.batch_mode.SetSelection(mode)
                    language = (frame.clone_lang, frame.design_lang, frame.auto_lang)[mode]
                    language.SetValue("Auto")
                    before = len(calls)
                    frame.OnGenBatch(None)
                    assert len(calls) == before
                    assert messages.call_args.args[0] == frame._("normalization_choose_language")
                    language.SetValue("Polish")
                    frame.OnGenBatch(None)
                    idle()
                    assert len(calls) == before + 1
                    assert calls[-1][1] == "Mam dwanaście jabłek [laughter]."
                    assert frame.batch_items[0].status == "done"
                    assert sf.info(frame.batch_items[0].output).frames == 2400
            print("Normalization: all desktop modes, both locales, Auto guard and batch WAV: OK")
        finally:
            frame.prog_timer.Stop()
            if frame.play_timer is not None:
                frame.play_timer.Stop()
            frame.Destroy()
            app.Yield()
    print(f"Synthetic fixtures: {scratch}")


if __name__ == "__main__":
    main()
