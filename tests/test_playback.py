"""Deterministic playback tests without opening an audio device or wx window."""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch


class Button:
    def __init__(self, label):
        self.label = label
        self.Show = Mock()
        self.Hide = Mock()

    def GetLabel(self):
        return self.label

    def SetLabel(self, label):
        self.label = label


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.wx = Mock()
        waveform = MagicMock(shape=(1, 100))
        waveform.__getitem__.return_value = list(range(100))
        namespace = {
            "wx": self.wx,
            "sd": Mock(),
            "os": SimpleNamespace(path=SimpleNamespace(exists=lambda path: True)),
            "load_waveform": lambda path: (waveform, 100),
        }
        tree = ast.parse(
            (Path(__file__).resolve().parents[1] / "omnisonic/app.py").read_text(encoding="utf-8")
        )
        names = {
            "OnPlayAudio",
            "TogglePlayFile",
            "OnStopAudio",
            "StopPlayFile",
            "_reset_generated_player",
            "_reset_reference_player",
        }
        methods = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
        exec(compile(ast.Module(body=methods, type_ignores=[]), "playback", "exec"), namespace)
        self.frame = SimpleNamespace(
            audio_data=list(range(100)),
            sample_rate=100,
            btn_play=Button("play"),
            btn_play_ref=Button("play_ref"),
            btn_stop_audio=Button("stop"),
            btn_stop_ref=Button("stop"),
            panel=Mock(),
            _play_sound_data=Mock(return_value=True),
            _stop_sound_device=Mock(),
            _=lambda key: key,
        )
        for name in names:
            setattr(self.frame, name, namespace[name].__get__(self.frame))

    def play(self, reference):
        if reference:
            self.frame.TogglePlayFile(
                self.frame.btn_play_ref,
                Mock(GetValue=lambda: "synthetic.wav"),
                self.frame.btn_stop_ref,
                self.frame.panel,
            )
        else:
            self.frame.OnPlayAudio(None)

    def test_pause_uses_monotonic_clock_including_zero_start(self):
        for reference in (False, True):
            for wall_time in (-1000, 1000):
                with self.subTest(reference=reference, wall_time=wall_time):
                    self.setUp()
                    with (
                        patch("time.monotonic", return_value=0.0) as clock,
                        patch("time.time", return_value=100.0) as wall,
                    ):
                        self.play(reference)
                        clock.return_value = 0.5
                        wall.return_value = wall_time
                        self.play(reference)
                    position = (
                        self.frame.ref_current_frame if reference else self.frame.current_frame
                    )
                    self.assertEqual(position, 50)
                    button = self.frame.btn_play_ref if reference else self.frame.btn_play
                    self.assertEqual(button.label, "resume_play")
                    self.play(reference)
                    self.assertEqual(
                        self.frame._play_sound_data.call_args.args[0], list(range(50, 100))
                    )

    def test_pause_after_end_resets_instead_of_resuming_empty_audio(self):
        for reference in (False, True):
            with self.subTest(reference=reference):
                self.setUp()
                with (
                    patch("time.monotonic", return_value=10.0) as clock,
                    patch("time.time", return_value=10.0) as wall,
                ):
                    self.play(reference)
                    clock.return_value = wall.return_value = 11.05
                    self.play(reference)
                button = self.frame.btn_play_ref if reference else self.frame.btn_play
                self.assertEqual(button.label, "play_ref" if reference else "play")
                self.frame._play_sound_data.assert_called_once()

    def test_pause_resume_accumulates_position_without_counting_pause(self):
        for reference in (False, True):
            with self.subTest(reference=reference):
                self.setUp()
                with patch("time.monotonic", return_value=10.0) as clock:
                    self.play(reference)
                    clock.return_value = 10.25
                    self.play(reference)
                    clock.return_value = 30.0
                    self.play(reference)
                    clock.return_value = 30.25
                    self.play(reference)
                position = self.frame.ref_current_frame if reference else self.frame.current_frame
                self.assertEqual(position, 50)


if __name__ == "__main__":
    unittest.main()
