"""Use real wx controls with synthetic audio and a mocked output device."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch


def main():
    root = Path(__file__).resolve().parents[1]
    scratch = Path(tempfile.mkdtemp(prefix="playback-ui-", dir=root / "trash"))
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import numpy as np
    import soundfile as sf
    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

    def load_waveform(path):
        data, rate = sf.read(path, always_2d=True, dtype="float32")
        return data.T, rate

    application = wx.App(False)
    frame = TestFrame(dict(DEFAULT_CONFIG, auto_transcribe_reference=False), None)
    application.SetTopWindow(frame)
    sound = Mock()
    first, second = scratch / "first.wav", scratch / "second.wav"
    sf.write(first, np.full(80000, 0.1, dtype=np.float32), 8000)
    sf.write(second, np.full(80000, 0.3, dtype=np.float32), 8000)
    frame.audio_data = np.full(80000, 0.5, dtype=np.float32)
    frame.sample_rate = 8000
    frame.clone_ref_audio.SetValue(str(first))

    def toggle(reference):
        if reference:
            frame.TogglePlayFile(
                frame.btn_play_ref, frame.clone_ref_audio, frame.btn_stop_ref, frame.tab_clone
            )
        else:
            frame.OnPlayAudio(None)

    try:
        with (
            patch.object(desktop, "sd", sound),
            patch.object(desktop, "load_waveform", load_waveform),
            patch.object(wx, "MessageBox", return_value=wx.OK),
            patch("time.monotonic", return_value=10.0) as clock,
        ):
            for reference in (False, True):
                for clicks in (0, 1, 2):
                    frame.cfg["language"] = "en"
                    frame.OnStopAudio(None)
                    for index in range(clicks):
                        clock.return_value = 10.0 + index * 0.25
                        toggle(reference)
                    # OnOpenSettings applies this configuration before the restart notice.
                    frame.cfg["language"] = "pl"
                    clock.return_value = 10.5
                    toggle(reference)
                    button = frame.btn_play_ref if reference else frame.btn_play
                    assert button.GetLabel() == frame._("resume_play" if clicks == 1 else "pause")

            for paused in (False, True):
                frame.OnStopAudio(None)
                frame.clone_ref_audio.SetValue(str(first))
                clock.return_value = 20.0
                toggle(True)
                if paused:
                    clock.return_value = 20.25
                    toggle(True)
                frame.clone_ref_audio.SetValue(str(second))
                assert frame._reference_playback_state == "stopped"
                assert frame.btn_play_ref.GetLabel() == frame._("play_ref")
                assert not frame.btn_stop_ref.IsShown()
                toggle(True)
                assert len(sound.play.call_args.args[0]) == 80000
                assert np.allclose(sound.play.call_args.args[0], 0.3, atol=0.001)

            frame.OnStopAudio(None)
            toggle(False)
            sound.stop.reset_mock()
            frame.clone_ref_audio.SetValue(str(first))
            sound.stop.assert_not_called()
            assert frame._generated_playback_state == "playing"
            assert frame.btn_play.GetLabel() == frame._("pause")
            frame.OnStopAudio(None)
            print("Playback language changes, source replacement and output isolation: OK")
    finally:
        if frame._reference_timer:
            frame._reference_timer.Stop()
        if frame._autoload_timer:
            frame._autoload_timer.Stop()
        if getattr(frame, "play_timer", None):
            frame.play_timer.Stop()
        reference_timer = getattr(frame, f"timer_{id(frame.btn_play_ref)}", None)
        if reference_timer:
            reference_timer.Stop()
        frame.Destroy()
        application.Yield()
        application.Destroy()


if __name__ == "__main__":
    main()
