"""Cross-feature desktop state transitions without real models or audio devices."""

from __future__ import annotations

import ast
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from omnisonic.validation import normalize_pasted_path


ROOT = Path(__file__).resolve().parents[1]


def handlers(names, **namespace):
    tree = ast.parse((ROOT / "omnisonic/app.py").read_text(encoding="utf-8"))
    nodes = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "desktop-workflow", "exec"), namespace)
    return namespace


class ModelStartupIntentTests(unittest.TestCase):
    def test_explicit_load_or_unload_cancels_a_deferred_startup_autoload(self):
        for loaded in (False, True):
            with self.subTest(loaded=loaded):
                wx = Mock()
                timer = Mock()
                frame = SimpleNamespace(
                    current_op=None,
                    model=object() if loaded else None,
                    cfg={},
                    _autoload_timer=timer,
                    _auto_reference_pending=True,
                    _EnsureModelWorker=Mock(),
                    _UnloadModelWorker=Mock(),
                    RunOperation=Mock(),
                )
                handler = handlers({"OnToggleModel"}, wx=wx)["OnToggleModel"]
                handler(frame, None)
                timer.Stop.assert_called_once_with()
                self.assertIsNone(frame._autoload_timer)
                frame.RunOperation.assert_called_once()

    def test_busy_rejected_toggle_does_not_cancel_startup_retry(self):
        timer = Mock()
        frame = SimpleNamespace(current_op=object(), _autoload_timer=timer)
        handler = handlers({"OnToggleModel"})["OnToggleModel"]
        handler(frame, None)
        timer.Stop.assert_not_called()
        self.assertIs(frame._autoload_timer, timer)


class RecordingDiscardTests(unittest.TestCase):
    def setUp(self):
        self.wx = Mock(ID_YES=1, YES_NO=2, NO_DEFAULT=4, ICON_WARNING=8, OK=16, ICON_ERROR=32)
        self.wx.MessageDialog.return_value.ShowModal.return_value = self.wx.ID_YES
        self.chunks = [object()]
        self.frame = SimpleNamespace(
            current_op=None,
            rec_stream=None,
            rec_data=self.chunks,
            rec_fs=44100,
            btn_rec_ref=Mock(),
            _closing=False,
            _confirming_close=False,
            _=lambda key: key,
            _CloseRecording=Mock(),
            _UpdateRecordingControls=Mock(),
            Log=Mock(),
        )

    def discard(self):
        handler = handlers({"OnDiscardRecording"}, wx=self.wx, logging=logging)[
            "OnDiscardRecording"
        ]
        handler(self.frame, None)

    def test_declining_keeps_pending_audio_and_confirming_unblocks_without_file_deletion(self):
        self.wx.MessageDialog.return_value.ShowModal.return_value = 0
        self.discard()
        self.assertIs(self.frame.rec_data, self.chunks)
        self.frame._CloseRecording.assert_not_called()
        self.wx.MessageDialog.return_value.Destroy.assert_called_once()
        self.wx.MessageDialog.return_value.ShowModal.return_value = self.wx.ID_YES
        self.discard()
        self.assertEqual(self.frame.rec_data, [])
        self.assertIsNone(self.frame.rec_fs)
        self.frame._UpdateRecordingControls.assert_called_once_with(self.frame.btn_rec_ref)
        self.frame.Log.assert_called_once_with("record_discarded")

    def test_failed_stream_shutdown_keeps_audio_for_retry(self):
        self.frame.rec_stream = Mock()
        self.frame._CloseRecording.side_effect = RuntimeError("Synthetic stop failure")
        self.discard()
        self.assertIs(self.frame.rec_data, self.chunks)
        self.frame.Log.assert_not_called()
        self.wx.MessageBox.assert_called_once()
        self.frame._UpdateRecordingControls.assert_called_once_with(self.frame.btn_rec_ref)

    def test_busy_or_reentrant_discard_cannot_open_a_confirmation(self):
        for flag in (
            "current_op",
            "_closing",
            "_confirming_close",
            "_confirming_discard_recording",
        ):
            with self.subTest(flag=flag):
                self.setUp()
                setattr(self.frame, flag, object())
                self.discard()
                self.wx.MessageDialog.assert_not_called()
                self.assertIs(self.frame.rec_data, self.chunks)

    def test_new_recording_published_during_confirmation_is_not_discarded(self):
        replacement = [object()]

        def replace():
            self.frame.rec_data = replacement
            return self.wx.ID_YES

        self.wx.MessageDialog.return_value.ShowModal.side_effect = replace
        self.discard()
        self.assertIs(self.frame.rec_data, replacement)
        self.frame._CloseRecording.assert_not_called()


class VoiceInstructionWorkflowTests(unittest.TestCase):
    def test_rejected_attribute_tags_preserve_previous_audio_before_clone_or_design(self):
        for name in ("OnGenClone", "OnGenDesign"):
            with self.subTest(name=name):
                frame = Mock(cfg={})
                frame._.side_effect = lambda key: key
                frame._CanUseModel.return_value = True
                frame._CheckTextNormalization.return_value = True
                frame._CheckVoiceInstruction.return_value = False
                frame.clone_text.GetValue.return_value = "Synthetic input"
                frame.design_text.GetValue.return_value = "Synthetic input"
                frame.clone_ref_audio.GetValue.return_value = "synthetic.wav"
                frame.clone_ref_text.GetValue.return_value = "Reference"
                frame.clone_instruct.GetValue.return_value = "calm narrator"
                frame.design_custom_instruct.GetValue.return_value = "calm narrator"
                frame.combo_presets.GetSelection.return_value = -1
                frame.design_combos = []
                wx = Mock(NOT_FOUND=-1)
                handler = handlers(
                    {name},
                    wx=wx,
                    os=SimpleNamespace(path=SimpleNamespace(exists=lambda path: True)),
                    normalize_pasted_path=normalize_pasted_path,
                )[name]
                handler(frame, None)
                frame._CheckVoiceInstruction.assert_called_once_with("calm narrator")
                frame._prepare_generation.assert_not_called()
                frame.RunModelOperation.assert_not_called()

    def test_validator_blank_valid_invalid_and_uninitialized_runtime_do_not_load_models(self):
        for instruction, validator, expected in (
            (None, None, True),
            ("  ", None, True),
            ("female, whisper", Mock(return_value="female, whisper"), True),
            ("calm narrator", Mock(side_effect=ValueError("Unsupported tag")), False),
            ("whisper", None, False),
        ):
            with self.subTest(instruction=instruction):
                wx = Mock(OK=1, ICON_ERROR=2)
                view = SimpleNamespace(
                    _=lambda key: "{error}" if key == "voice_instruction_invalid" else key
                )
                handler = handlers(
                    {"_CheckVoiceInstruction"}, wx=wx, resolve_voice_instruction=validator
                )["_CheckVoiceInstruction"]
                self.assertEqual(handler(view, instruction), expected)
                if expected:
                    wx.MessageBox.assert_not_called()
                else:
                    wx.MessageBox.assert_called_once()


class GenerationPreparationTests(unittest.TestCase):
    def test_rejected_start_does_not_clear_previous_audio_or_stop_playback(self):
        for worker_busy, recording_busy in ((True, False), (False, True)):
            with self.subTest(worker_busy=worker_busy, recording_busy=recording_busy):
                previous_audio = object()
                view = Mock(
                    current_op=object() if worker_busy else None,
                    rec_stream=None,
                    rec_data=[object()] if recording_busy else [],
                    audio_data=previous_audio,
                )
                wx = Mock(OK=1, ICON_WARNING=2)
                methods = handlers({"_prepare_generation", "_CanStartGeneration"}, wx=wx)
                view._CanStartGeneration = methods["_CanStartGeneration"].__get__(view)
                handler = methods["_prepare_generation"]
                result = handler(view)
                self.assertIs(view.audio_data, previous_audio)
                self.assertIs(result, False)
                view.OnStopAudio.assert_not_called()
                wx.Bell.assert_called_once()


if __name__ == "__main__":
    unittest.main()
