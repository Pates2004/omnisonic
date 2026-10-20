"""Copy-as-path references through GUI handlers without devices or model imports."""

from __future__ import annotations

import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from omnisonic.batch import BatchInput, BatchResult

from tests.materials import scratch_directory
from tests.test_output_paths import handler


class ReferencePathTests(unittest.TestCase):
    def setUp(self):
        self.folder = scratch_directory("reference-path-ui-")
        self.source = self.folder / "reference & O'Brien.wav"
        self.source.write_bytes(b"Synthetic path fixture, never decoded")
        self.quoted = f'  "{self.source}"  '
        self.wx = Mock(NOT_FOUND=-1, OK=1, ICON_ERROR=2)
        self.frame = Mock(cfg={})
        self.frame._.side_effect = lambda key: key
        self.frame._CanUseModel.return_value = True
        self.frame.current_op = None
        self.frame.clone_ref_audio.GetValue.return_value = self.quoted
        self.frame.clone_ref_text.GetValue.return_value = ""
        self.frame._reference_revision = 1

    def test_clone_uses_reference_without_copy_as_path_wrapper(self):
        frame = self.frame
        frame.clone_text.GetValue.return_value = "Synthetic narration"
        frame.clone_lang.GetValue.return_value = "Auto"
        frame.clone_instruct.GetValue.return_value = ""
        frame.combo_presets.GetSelection.return_value = -1
        handler("app.py", "OnGenClone", wx=self.wx, os=os)(frame, None)
        self.wx.MessageBox.assert_not_called()
        frame.RunModelOperation.assert_called_once()
        self.assertEqual(frame.RunModelOperation.call_args.args[5], str(self.source))

    def test_manual_transcription_accepts_wrapper_and_applies_unchanged_source_result(self):
        frame = self.frame
        handler("app.py", "OnTranscribeReference", wx=self.wx, os=os)(frame, None)
        self.wx.MessageBox.assert_not_called()
        frame.RunModelOperation.assert_called_once()
        self.assertEqual(frame.RunModelOperation.call_args.args[3], str(self.source))
        frame.RunModelOperation.call_args.kwargs["success_callback"]("Synthetic transcript")
        frame.clone_ref_text.SetValue.assert_called_once_with("Synthetic transcript")

    def test_automatic_transcription_accepts_copy_as_path_wrapper(self):
        frame = self.frame
        frame.cfg["auto_transcribe_reference"] = True
        frame.IsBeingDeleted.return_value = False
        frame._auto_reference_pending = True
        frame.rec_stream = None
        frame.rec_data = []
        wx = SimpleNamespace(Dialog=type("Dialog", (), {}), GetActiveWindow=lambda: None)
        handler("app.py", "_MaybeAutoTranscribeReference", wx=wx, os=os)(frame)
        frame.OnTranscribeReference.assert_called_once_with(None, automatic=True)

    def test_reference_playback_accepts_copy_as_path_wrapper(self):
        frame = self.frame
        frame._reference_playback_state = "stopped"
        frame._play_sound_data.return_value = True
        loader = Mock(return_value=(SimpleNamespace(shape=(2, 8), T=[0.1] * 8), 8))
        handler("app.py", "TogglePlayFile", wx=self.wx, os=os, load_waveform=loader)(
            frame, Mock(), frame.clone_ref_audio, Mock(), Mock()
        )
        self.wx.MessageBox.assert_not_called()
        loader.assert_called_once_with(str(self.source))
        self.assertEqual(frame._reference_playback_state, "playing")

    def test_batch_clone_accepts_the_same_reference_path_as_single_generation(self):
        source_text = self.folder / "input.txt"
        source_text.write_text("Synthetic narration", encoding="utf-8")
        frame = self.frame
        frame.batch_items = [BatchResult(str(source_text))]
        frame.batch_mode.GetSelection.return_value = 0
        frame.clone_lang.GetValue.return_value = "Auto"
        frame.combo_presets.GetSelection.return_value = -1
        frame.clone_instruct.GetValue.return_value = ""
        frame.batch_output.GetValue.return_value = str(self.folder / "output")
        handler(
            "batch_ui.py",
            "OnGenBatch",
            wx=self.wx,
            os=os,
            datetime=datetime,
            uuid4=uuid4,
            BatchInput=BatchInput,
        )(frame, None)
        self.wx.MessageBox.assert_not_called()
        frame.RunModelOperation.assert_called_once()
        self.assertEqual(frame.RunModelOperation.call_args.args[6], (None, str(self.source), None))

    def test_batch_rejects_invalid_voice_attributes_before_stopping_audio_or_dispatch(self):
        frame = self.frame
        frame.batch_items = [BatchResult(str(self.folder / "input.txt"))]
        frame.batch_mode.GetSelection.return_value = 0
        frame.clone_lang.GetValue.return_value = "Auto"
        frame.combo_presets.GetSelection.return_value = -1
        frame.clone_instruct.GetValue.return_value = "unsupported arbitrary prose"
        frame._CheckVoiceInstruction.return_value = False
        frame.batch_output.GetValue.return_value = str(self.folder / "output")
        handler(
            "batch_ui.py",
            "OnGenBatch",
            wx=self.wx,
            os=os,
            datetime=datetime,
            uuid4=uuid4,
            BatchInput=BatchInput,
        )(frame, None)
        frame._CheckVoiceInstruction.assert_called_once_with("unsupported arbitrary prose")
        frame.OnStopAudio.assert_not_called()
        frame.RunModelOperation.assert_not_called()

    def test_batch_rejected_start_preserves_playback_and_does_not_dispatch(self):
        frame = self.frame
        frame._CanStartGeneration.return_value = False
        frame.batch_items = [BatchResult(str(self.folder / "input.txt"))]
        frame.batch_mode.GetSelection.return_value = 0
        frame.clone_lang.GetValue.return_value = "Auto"
        frame.combo_presets.GetSelection.return_value = -1
        frame.clone_instruct.GetValue.return_value = ""
        frame.batch_output.GetValue.return_value = str(self.folder / "output")
        handler(
            "batch_ui.py",
            "OnGenBatch",
            wx=self.wx,
            os=os,
            datetime=datetime,
            uuid4=uuid4,
            BatchInput=BatchInput,
        )(frame, None)
        frame._CanStartGeneration.assert_called_once_with()
        frame.OnStopAudio.assert_not_called()
        frame.RunModelOperation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
