"""Independent batch voice inputs through real handlers, without wx or models."""

from __future__ import annotations

import ast
import logging
import os
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

from omnisonic.batch import BatchInput, BatchResult
from omnisonic.i18n import load_locales, translate
from omnisonic.validation import (
    normalize_pasted_path,
    output_directory_path,
    safe_child_path,
    validation_error_message,
)
from tests.materials import scratch_directory
from tests.test_preset_selection import PresetControl, load_handler


ROOT = Path(__file__).resolve().parents[1]


def batch_type(source_text=None, **overrides):
    source = ROOT / "omnisonic/batch_ui.py"
    tree = ast.parse(source_text if source_text is not None else source.read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    namespace = dict(
        wx=SimpleNamespace(NOT_FOUND=-1, OK=1, ICON_ERROR=2, MessageBox=Mock()),
        Path=Path,
        BatchInput=BatchInput,
        BatchResult=BatchResult,
        datetime=datetime,
        uuid4=uuid4,
        normalize_pasted_path=normalize_pasted_path,
        output_directory_path=output_directory_path,
        safe_child_path=safe_child_path,
        validation_error_message=validation_error_message,
        default_audio_directory=lambda kind: Path("synthetic-output"),
    )
    namespace.update(overrides)
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[]))
    exec(compile(module, str(source), "exec"), namespace)
    return namespace[node.name]


def value_control(value="", *, selection=0, data=None):
    control = Mock()
    control.GetValue.return_value = value
    control.GetSelection.return_value = selection
    control.GetClientData.return_value = data
    return control


class CustomBatchDispatchTests(unittest.TestCase):
    def setUp(self):
        self.scratch = scratch_directory("custom-batch-handler-")
        self.reference = self.scratch / "reference & O'Brien.wav"
        self.reference.write_bytes(b"Synthetic path input, not decoded")
        self.preset_directory = self.scratch / "presets"
        self.preset_directory.mkdir()
        self.preset = self.preset_directory / "Independent.pt"
        self.preset.write_bytes(b"Synthetic preset, not loaded")
        self.wx = SimpleNamespace(NOT_FOUND=-1, OK=1, ICON_ERROR=2, MessageBox=Mock())
        self.frame = batch_type(wx=self.wx, PRESETS_DIR=self.preset_directory)()
        frame = self.frame
        frame.cfg = {"normalize_text": False}
        frame._ = lambda key: key
        frame._CanStartGeneration = Mock(return_value=True)
        frame._CanUseModel = Mock(return_value=True)
        frame._CheckTextNormalization = Mock(return_value=True)
        frame._CheckVoiceInstruction = Mock(return_value=True)
        frame.GetGenConfig = Mock(return_value=object())
        frame._GetGenerationSeed = Mock(return_value=123)
        frame.OnStopAudio = Mock()
        frame.RunModelOperation = Mock()
        frame._BatchFinished = Mock()
        frame.current_op = None
        frame.batch_items = [BatchResult(str(self.scratch / "sentence.txt"))]
        frame.batch_mode = value_control(selection=3)
        frame.batch_custom_voice = value_control(selection=0)
        frame.batch_custom_preset = value_control(selection=0)
        frame.batch_custom_audio = value_control(f'  "{self.reference}"  ')
        frame.batch_custom_text = value_control("  Independent transcript  ")
        frame.batch_custom_language = value_control("English")
        frame.batch_custom_instruction = value_control("whisper")
        frame.batch_output = value_control(str(self.scratch / "output"))
        frame.batch_preserve_structure = value_control(True)
        frame.chk_duration = value_control(False)
        frame.spin_duration = value_control(5.0)
        frame.spin_speed = value_control(1.25)
        frame.design_combos = []
        # A custom dispatch must never consult another tab's voice controls.
        for name in (
            "clone_lang",
            "design_lang",
            "auto_lang",
            "combo_presets",
            "clone_ref_audio",
            "clone_ref_text",
            "clone_instruct",
            "design_custom_instruct",
        ):
            control = Mock()
            control.GetValue.side_effect = AssertionError(f"Borrowed main-tab control: {name}")
            control.GetSelection.side_effect = AssertionError(f"Borrowed main-tab control: {name}")
            setattr(frame, name, control)

    def dispatch(self):
        self.frame.OnGenBatch(None)

    def dispatched(self):
        self.frame.RunModelOperation.assert_called_once()
        return self.frame.RunModelOperation.call_args.args

    def test_custom_reference_language_transcript_and_instruction_are_independent(self):
        self.dispatch()
        args = self.dispatched()
        self.assertEqual(args[6], (None, str(self.reference), "Independent transcript"))
        self.assertEqual(args[5]["language"], "English")
        self.assertEqual(args[5]["instruct"], "whisper")
        self.assertEqual(args[5]["speed"], 1.25)
        self.assertNotIn("duration", args[5])
        self.assertIs(args[5]["generation_config"], self.frame.GetGenConfig.return_value)
        self.assertEqual(args[-1], 123)
        self.wx.MessageBox.assert_not_called()

    def test_selected_custom_preset_wins_over_its_unused_audio_fields(self):
        self.frame.batch_custom_preset.GetSelection.return_value = 1
        self.frame.batch_custom_preset.GetClientData.return_value = self.preset.name
        self.frame.batch_custom_audio.GetValue.side_effect = AssertionError("Read unused audio")
        self.frame.batch_custom_text.GetValue.side_effect = AssertionError("Read unused transcript")
        self.dispatch()
        self.assertEqual(self.dispatched()[6], (str(self.preset.resolve()), None, None))

    def test_custom_design_and_automatic_do_not_require_a_reference(self):
        for voice in (1, 2):
            with self.subTest(voice=voice):
                self.frame.RunModelOperation.reset_mock()
                self.frame.batch_custom_voice.GetSelection.return_value = voice
                for name in ("batch_custom_preset", "batch_custom_audio", "batch_custom_text"):
                    control = getattr(self.frame, name)
                    control.GetValue.side_effect = AssertionError("Read unused clone reference")
                    control.GetSelection.side_effect = AssertionError("Read unused clone preset")
                self.dispatch()
                args = self.dispatched()
                self.assertIsNone(args[6])
                if voice == 1:
                    self.assertEqual(args[5]["instruct"], "whisper")
                else:
                    self.assertNotIn("instruct", args[5])

    def test_auto_language_is_omitted_and_blank_transcript_requests_asr(self):
        self.frame.batch_custom_language.GetValue.return_value = "Auto"
        self.frame.batch_custom_text.GetValue.return_value = " \n "
        self.frame.batch_custom_instruction.GetValue.return_value = ""
        self.dispatch()
        args = self.dispatched()
        self.assertNotIn("language", args[5])
        self.assertNotIn("instruct", args[5])
        self.assertEqual(args[6], (None, str(self.reference), None))

    def test_dispatch_snapshots_inputs_before_control_values_change(self):
        self.dispatch()
        args = self.dispatched()
        self.frame.batch_custom_audio.GetValue.return_value = "other.wav"
        self.frame.batch_custom_text.GetValue.return_value = "Changed"
        self.frame.batch_custom_language.GetValue.return_value = "Polish"
        self.frame.batch_custom_instruction.GetValue.return_value = "shout"
        self.assertEqual(args[6], (None, str(self.reference), "Independent transcript"))
        self.assertEqual(args[5]["language"], "English")
        self.assertEqual(args[5]["instruct"], "whisper")

    def test_missing_custom_reference_stops_before_playback_or_model_dispatch(self):
        for value in ("", str(self.scratch / "missing.wav"), str(self.scratch)):
            with self.subTest(reference=value):
                self.frame.batch_custom_audio.GetValue.return_value = value
                self.dispatch()
                self.frame.RunModelOperation.assert_not_called()
                self.frame.OnStopAudio.assert_not_called()
                self.assertEqual(self.wx.MessageBox.call_args.args[0], "err_no_audio_preset")

    def test_custom_normalization_validation_uses_its_own_language(self):
        self.frame._CheckTextNormalization.return_value = False
        self.dispatch()
        self.frame._CheckTextNormalization.assert_called_once_with("English")
        self.frame.OnStopAudio.assert_not_called()
        self.frame.RunModelOperation.assert_not_called()

    def test_invalid_custom_voice_instruction_blocks_dispatch(self):
        self.frame._CheckVoiceInstruction.return_value = False
        self.dispatch()
        self.frame._CheckVoiceInstruction.assert_called_once_with("whisper")
        self.frame.OnStopAudio.assert_not_called()
        self.frame.RunModelOperation.assert_not_called()

    def test_validation_messages_are_localized_in_both_interface_languages(self):
        locales = load_locales((ROOT / "langs",))
        self.frame.batch_custom_voice.GetSelection.return_value = -1
        for language in ("pl", "en"):
            with self.subTest(language=language):
                self.frame._ = lambda key, lang=language: translate(locales, lang, key)
                self.dispatch()
                self.assertEqual(
                    self.wx.MessageBox.call_args.args[0], locales[language]["batch_invalid_mode"]
                )
                self.frame.RunModelOperation.assert_not_called()

    def test_custom_preset_cannot_escape_the_program_preset_directory(self):
        for filename in ("../outside.pt", r"..\outside.pt", str(self.scratch / "outside.pt")):
            with self.subTest(filename=filename):
                self.wx.MessageBox.reset_mock()
                self.frame.batch_custom_preset.GetSelection.return_value = 1
                self.frame.batch_custom_preset.GetClientData.return_value = filename
                self.dispatch()
                self.frame.RunModelOperation.assert_not_called()
                self.frame.OnStopAudio.assert_not_called()
                self.assertTrue(self.wx.MessageBox.called)

    def test_custom_preset_requests_link_rejection_before_dispatch(self):
        self.frame.batch_custom_preset.GetSelection.return_value = 1
        self.frame.batch_custom_preset.GetClientData.return_value = self.preset.name
        reject = Mock(side_effect=ValueError("Synthetic linked preset rejection"))
        self.frame.OnGenBatch.__func__.__globals__["safe_child_path"] = reject
        self.dispatch()
        reject.assert_called_once_with(self.preset_directory, self.preset.name, reject_links=True)
        self.frame.RunModelOperation.assert_not_called()
        self.frame.OnStopAudio.assert_not_called()

    def test_invalid_source_or_custom_voice_selection_does_not_dispatch(self):
        for source, voice in ((-1, 0), (4, 0), (3, -1), (3, 3)):
            with self.subTest(source=source, voice=voice):
                self.frame.batch_mode.GetSelection.return_value = source
                self.frame.batch_custom_voice.GetSelection.return_value = voice
                self.dispatch()
                self.frame.RunModelOperation.assert_not_called()
                self.frame.OnStopAudio.assert_not_called()
                self.assertEqual(self.wx.MessageBox.call_args.args[0], "batch_invalid_mode")

    def test_original_three_source_modes_keep_their_main_tab_inputs(self):
        for source in (0, 1, 2):
            with self.subTest(source=source):
                self.frame.RunModelOperation.reset_mock()
                self.frame.batch_mode.GetSelection.return_value = source
                self.frame.batch_custom_voice.GetSelection.side_effect = AssertionError(
                    "Read custom voice for a main-tab mode"
                )
                for name in ("clone_lang", "design_lang", "auto_lang"):
                    setattr(self.frame, name, value_control("Polish"))
                self.frame.combo_presets = value_control(selection=0)
                self.frame.clone_ref_audio = value_control(str(self.reference))
                self.frame.clone_ref_text = value_control("Main-tab reference")
                self.frame.clone_instruct = value_control("shout")
                self.frame.design_custom_instruct = value_control("female")
                self.dispatch()
                args = self.dispatched()
                self.assertEqual(args[5]["language"], "Polish")
                if source == 0:
                    self.assertEqual(args[6], (None, str(self.reference), "Main-tab reference"))
                    self.assertEqual(args[5]["instruct"], "shout")
                elif source == 1:
                    self.assertIsNone(args[6])
                    self.assertEqual(args[5]["instruct"], "female")
                else:
                    self.assertIsNone(args[6])
                    self.assertNotIn("instruct", args[5])

    def test_rejected_start_does_not_read_inputs_or_stop_playback(self):
        self.frame._CanStartGeneration.return_value = False
        self.dispatch()
        self.frame.batch_mode.GetSelection.assert_not_called()
        self.frame.batch_custom_audio.GetValue.assert_not_called()
        self.frame.OnStopAudio.assert_not_called()
        self.frame.RunModelOperation.assert_not_called()

    def test_new_audio_clears_only_the_custom_reference_transcript(self):
        event = Mock()
        self.frame.OnBatchReferenceChanged(event)
        self.frame.batch_custom_text.ChangeValue.assert_called_once_with("")
        self.frame.clone_ref_text.ChangeValue.assert_not_called()
        event.Skip.assert_called_once()


class CustomBatchSetupTests(unittest.TestCase):
    def test_default_choice_is_custom_without_renumbering_existing_sources(self):
        wx = MagicMock()
        wx.Choice.side_effect = lambda *args, **kwargs: MagicMock()
        frame = Mock(cfg={"generated_audio_directory": "synthetic-output"})
        frame._.side_effect = lambda key: key
        frame.clone_lang.GetItems.return_value = ["Auto", "English", "Polish"]
        batch_type(wx=wx).SetupBatchTab(frame, Mock())
        frame.batch_mode.SetSelection.assert_called_once_with(3)
        frame.batch_custom_voice.SetSelection.assert_called_once_with(0)
        frame.batch_custom_language.SetValue.assert_called_once_with("Auto")
        choices = [call.kwargs.get("choices") for call in wx.Choice.call_args_list]
        self.assertIn(["tab_clone", "tab_design", "tab_auto", "batch_custom"], choices)

    def test_operation_and_recording_busy_states_disable_the_custom_parent(self):
        handler = load_handler("_set_operation_controls_enabled", {})
        for enabled, stream, audio, expected in (
            (False, None, (), False),
            (True, object(), (), False),
            (True, None, [b"Pending synthetic audio"], False),
            (True, None, (), True),
        ):
            with self.subTest(enabled=enabled, stream=bool(stream), audio=bool(audio)):
                frame = SimpleNamespace(
                    rec_stream=stream, rec_data=audio, batch_custom_panel=Mock()
                )
                handler(frame, enabled)
                frame.batch_custom_panel.Enable.assert_called_once_with(expected)


class CustomBatchPresetRefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = scratch_directory("custom-batch-presets-")
        for name in ("Alpha.pt", "Bravo.pt"):
            (self.directory / name).write_bytes(b"Synthetic preset")
        self.frame = SimpleNamespace(
            combo_presets=PresetControl(),
            list_presets=PresetControl(),
            batch_custom_preset=PresetControl(),
            cfg={"preset_display_mode": "name"},
            current_op=None,
            _=lambda key: key,
            _set_operation_controls_enabled=Mock(),
            _UpdateBatchCustomControls=Mock(),
        )
        namespace = dict(
            wx=SimpleNamespace(NOT_FOUND=-1),
            PRESETS_DIR=self.directory,
            safe_child_path=safe_child_path,
            os=os,
            logging=logging,
        )
        self.frame.RefreshPresets = load_handler("RefreshPresets", namespace).__get__(self.frame)

    def select(self, control, filename):
        index = next(
            index for index in range(control.GetCount()) if control.GetClientData(index) == filename
        )
        control.SetSelection(index)

    def test_refresh_preserves_three_independent_preset_identities(self):
        self.frame.RefreshPresets()
        self.assertEqual(self.frame.batch_custom_preset.GetCount(), 3)
        self.select(self.frame.combo_presets, "Alpha.pt")
        self.select(self.frame.list_presets, "Bravo.pt")
        self.select(self.frame.batch_custom_preset, "Bravo.pt")
        (self.directory / "Aardvark.pt").touch()
        self.frame.cfg["preset_display_mode"] = "path"
        self.frame.RefreshPresets()
        for control, expected in (
            (self.frame.combo_presets, "Alpha.pt"),
            (self.frame.list_presets, "Bravo.pt"),
            (self.frame.batch_custom_preset, "Bravo.pt"),
        ):
            self.assertEqual(control.GetClientData(control.GetSelection()), expected)
        control = self.frame.batch_custom_preset
        self.assertEqual(control.items[control.GetSelection()][0], str(self.directory / "Bravo.pt"))

    def test_deleted_custom_preset_falls_back_to_new_audio_without_resetting_clone(self):
        self.frame.RefreshPresets()
        self.select(self.frame.combo_presets, "Alpha.pt")
        self.select(self.frame.batch_custom_preset, "Bravo.pt")
        (self.directory / "Bravo.pt").unlink()
        self.frame.RefreshPresets()
        self.assertEqual(self.frame.batch_custom_preset.GetSelection(), 0)
        self.assertIsNone(self.frame.batch_custom_preset.GetClientData(0))
        self.assertEqual(self.frame.combo_presets.GetClientData(1), "Alpha.pt")


if __name__ == "__main__":
    unittest.main()
