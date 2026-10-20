"""Invisible keyboard/UI flow using synthetic subtitle audio, with no model download."""

from __future__ import annotations

import json
import os
import sys
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.materials import scratch_directory


def main():
    scratch = scratch_directory("subtitle-ui-")
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import numpy as np
    import soundfile as sf
    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG
    from omnivoice.utils.voice_design import resolve_instruct
    from tests.test_prompt_cache import Prompt, Tokens

    desktop.np = np
    desktop.resolve_voice_instruction = resolve_instruct
    desktop.OmniVoiceGenerationConfig = SimpleNamespace
    application = wx.App(False)
    application.SetExitOnFrameDelete(False)
    calls = []

    class Model:
        sampling_rate = 24000
        device = "cpu"
        _asr_pipe = None

        def generate(self, **kwargs):
            resolve_instruct(kwargs.get("instruct"))
            calls.append(kwargs)
            if kwargs["text"] == "Plain text.":
                return [np.full(2400, 0.1, dtype=np.float32)]
            assert kwargs["duration"] in (0.4, 0.6)
            assert "speed" not in kwargs
            assert kwargs["generation_config"].pad_duration == 0
            assert not kwargs["generation_config"].postprocess_output
            frames = round(kwargs["duration"] * self.sampling_rate) - 120
            return [np.full(frames, 0.2, dtype=np.float32)]

        def create_voice_clone_prompt(self, **kwargs):
            return Prompt(Tokens([1, 2], "cpu"), kwargs["ref_text"], 0.1)

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

    def idle(frame):
        deadline = time.monotonic() + 30
        while frame.current_op is not None:
            application.Yield()
            if time.monotonic() >= deadline:
                raise TimeoutError("Subtitle UI worker did not finish")
            time.sleep(0.01)
        application.Yield()

    sources = scratch / "Movie"
    nested = sources / "Subtitles"
    nested.mkdir(parents=True)
    (nested / "movie.srt").write_text(
        "1\n00:00:00,500 --> 00:00:00,900\n<i>First.</i>\n\n"
        "2\n00:00:01,500 --> 00:00:02,100\nSecond.\n",
        encoding="utf-8",
    )
    (nested / "movie.vtt").write_text(
        "WEBVTT\n\n00:00.500 --> 00:00.900\n<v Narrator>First.</v>\n\n"
        "00:01.500 --> 00:02.100\nSecond.\n",
        encoding="utf-8",
    )
    (sources / "plain.txt").write_text("Plain text.", encoding="utf-8")
    reference = scratch / "reference.wav"
    sf.write(reference, np.zeros(2400, dtype=np.float32), 24000)
    modules = {"omnivoice": SimpleNamespace(VoiceClonePrompt=Prompt)}
    with patch.dict(sys.modules, modules), patch.object(wx, "Bell"):
        for language in ("pl", "en"):
            config = deepcopy(DEFAULT_CONFIG)
            config.update(language=language, show_progress=False, auto_transcribe_reference=False)
            frame = TestFrame(config, None)
            try:
                frame.model = Model()
                frame.clone_ref_audio.SetValue(str(reference))
                frame.clone_ref_text.SetValue("Reference.")
                frame.design_custom_instruct.SetValue("whisper")
                frame.batch_output.SetValue(f'"{scratch / (language + " narration output")}"')
                frame.notebook.SetSelection(frame.notebook.FindPage(frame.tab_batch))
                assert frame.batch_list.GetName() == frame._("batch_queue")
                assert "*.srt" in frame._("batch_text_filter")
                assert "*.vtt" in frame._("batch_text_filter")
                with patch.object(wx, "MessageBox", return_value=wx.OK) as messages:
                    frame.OnShowSubtitleHelp(None)
                    assert messages.call_args.args[:2] == (
                        frame._("subtitle_help_body"),
                        frame._("subtitle_help_title"),
                    )
                    for mode in (0, 1, 2):
                        calls.clear()
                        frame.OnBatchClear(None)
                        frame._scan_batch_inputs([str(sources)])
                        idle(frame)
                        assert len(frame.batch_items) == 3
                        frame.batch_mode.SetSelection(mode)
                        frame.OnShortcutGenerate(None)
                        idle(frame)
                        assert all(item.status == "done" for item in frame.batch_items), [
                            item.error for item in frame.batch_items
                        ]
                        assert len(calls) == 5
                        for item in frame.batch_items:
                            if item.source.endswith(".txt"):
                                continue
                            output = Path(item.output)
                            assert output.name in {"movie.wav", "movie (2).wav"}
                            assert output.parent.name == "Subtitles"
                            audio, rate = sf.read(output, dtype="float32")
                            assert rate == 24000 and len(audio) == 50400
                            assert np.all(audio[:12000] == 0)
                            assert np.all(audio[21480:36000] == 0)
                            assert np.all(audio[-120:] == 0)
                            assert np.any(audio[12000:21480] != 0)
                            report = json.loads(
                                (output.parents[2] / "batch_report.json").read_text()
                            )
                            assert all(row["status"] == "done" for row in report["files"])
                        assert frame.btn_gen_batch.IsEnabled() and frame.batch_list.IsEnabled()
            finally:
                with patch.object(wx, "MessageBox", return_value=wx.OK):
                    idle(frame)
                frame.Destroy()
                application.Yield()
    application.Destroy()
    print(
        "Subtitle UI: both locales, Help, Ctrl+G, clone/design/auto, mixed inputs and exact WAV: OK"
    )
    print(f"Synthetic fixtures: {scratch}")


if __name__ == "__main__":
    main()
