"""Clone preset creation and shared deletion use selected identity and safe state."""

from __future__ import annotations

import ast
import logging
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from omnisonic.validation import (
    normalize_pasted_path,
    preset_filename,
    safe_child_path,
    validation_error_message,
)
from tests.materials import scratch_directory
from tests.test_preset_selection import PresetControl, load_handler


ROOT = Path(__file__).resolve().parents[1]


class ClonePresetTests(unittest.TestCase):
    def setUp(self):
        self.directory = scratch_directory("clone-preset-ui-")
        self.wx = SimpleNamespace(
            NOT_FOUND=-1,
            WXK_DELETE=127,
            OK=1,
            ICON_ERROR=2,
            ICON_INFORMATION=4,
            Bell=Mock(),
            MessageBox=Mock(),
        )
        self.namespace = dict(
            wx=self.wx,
            PRESETS_DIR=self.directory,
            safe_child_path=safe_child_path,
            validation_error_message=validation_error_message,
            logging=logging,
            os=os,
        )
        self.frame = SimpleNamespace(
            combo_presets=PresetControl(),
            list_presets=PresetControl(),
            cfg={"preset_display_mode": "name"},
            current_op=None,
            rec_stream=None,
            rec_data=(),
            _=lambda key: key,
            _CheckDeleteWarning=Mock(return_value=True),
            _set_operation_controls_enabled=Mock(),
        )
        tree = ast.parse((ROOT / "omnisonic/app.py").read_text(encoding="utf-8"))
        available = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        for name in (
            "RefreshPresets",
            "_CanModifyPresets",
            "_SelectedPreset",
            "_SelectedManagedPreset",
            "_DeletePreset",
            "_OnPresetDeleteKey",
            "OnClonePresetKeyDown",
            "OnPresetManagerKeyDown",
            "OnDelPreset",
            "OnDelAllPresets",
        ):
            if name in available:
                setattr(self.frame, name, load_handler(name, self.namespace).__get__(self.frame))
        for name in ("Alpha.pt", "Bravo.pt"):
            (self.directory / name).write_bytes(b"synthetic preset")
        self.frame.RefreshPresets()
        self.frame.combo_presets.SetSelection(2)
        self.frame.list_presets.SetSelection(0)

    def key(self, *, shift=False, code=127):
        return SimpleNamespace(GetKeyCode=lambda: code, ShiftDown=lambda: shift, Skip=Mock())

    def test_clone_deletes_only_combo_selection_not_manager_selection(self):
        self.assertTrue(hasattr(self.frame, "OnClonePresetKeyDown"))
        self.frame.OnClonePresetKeyDown(self.key())
        self.assertTrue((self.directory / "Alpha.pt").is_file())
        self.assertFalse((self.directory / "Bravo.pt").exists())
        self.frame._CheckDeleteWarning.assert_called_once()
        self.assertEqual(self.frame.combo_presets.GetSelection(), 0)
        self.assertEqual(self.frame.list_presets.GetClientData(0), "Alpha.pt")

    def test_none_entry_and_other_keys_do_not_delete_or_warn(self):
        self.assertTrue(hasattr(self.frame, "OnClonePresetKeyDown"))
        self.frame.combo_presets.SetSelection(0)
        for event in (self.key(), self.key(shift=True), self.key(code=13)):
            self.frame.OnClonePresetKeyDown(event)
            event.Skip.assert_called_once()
        self.assertEqual(len(list(self.directory.glob("*.pt"))), 2)
        self.frame._CheckDeleteWarning.assert_not_called()

    def test_clone_delete_declined_or_warning_disabled_matches_manager_policy(self):
        self.assertTrue(hasattr(self.frame, "OnClonePresetKeyDown"))
        self.frame._CheckDeleteWarning.return_value = False
        self.frame.OnClonePresetKeyDown(self.key())
        self.assertTrue((self.directory / "Bravo.pt").exists())
        self.frame._CheckDeleteWarning.return_value = True
        self.frame.OnClonePresetKeyDown(self.key())
        self.assertFalse((self.directory / "Bravo.pt").exists())
        self.assertEqual(self.frame._CheckDeleteWarning.call_count, 2)

    def test_shift_delete_skips_warning_for_both_lists(self):
        self.assertTrue(hasattr(self.frame, "OnClonePresetKeyDown"))
        self.frame._CheckDeleteWarning.return_value = False
        self.frame.OnClonePresetKeyDown(self.key(shift=True))
        self.frame.OnPresetManagerKeyDown(self.key(shift=True))
        self.assertEqual(list(self.directory.glob("*.pt")), [])
        self.frame._CheckDeleteWarning.assert_not_called()

    def test_manager_buttons_and_keys_still_use_manager_identity(self):
        for name in ("OnDelPreset", "OnPresetManagerKeyDown"):
            with self.subTest(handler=name):
                selected = self.directory / "Alpha.pt"
                selected.write_bytes(b"synthetic preset")
                self.frame.RefreshPresets()
                self.frame.list_presets.SetSelection(0)
                getattr(self.frame, name)(self.key())
                self.assertFalse(selected.exists())
                self.assertTrue((self.directory / "Bravo.pt").exists())
                self.assertEqual(self.frame.combo_presets.GetClientData(1), "Bravo.pt")

    def test_busy_or_recording_blocks_all_preset_delete_routes(self):
        for name, value in (
            ("current_op", object()),
            ("rec_stream", object()),
            ("rec_data", [b"unsaved recording"]),
        ):
            for handler in ("OnDelPreset", "OnDelAllPresets", "OnPresetManagerKeyDown"):
                with self.subTest(state=name, handler=handler):
                    setattr(self.frame, name, value)
                    getattr(self.frame, handler)(self.key(shift=True))
                    self.assertEqual(len(list(self.directory.glob("*.pt"))), 2)
                    setattr(self.frame, name, None if name != "rec_data" else ())
        self.frame._CheckDeleteWarning.assert_not_called()

    def test_clone_busy_or_recording_blocks_delete_before_selection(self):
        self.assertTrue(hasattr(self.frame, "OnClonePresetKeyDown"))
        for name, value in (("current_op", object()), ("rec_stream", object()), ("rec_data", [1])):
            with self.subTest(state=name):
                setattr(self.frame, name, value)
                self.frame.OnClonePresetKeyDown(self.key(shift=True))
                self.assertTrue((self.directory / "Bravo.pt").is_file())
                setattr(self.frame, name, None if name != "rec_data" else ())
        self.frame._CheckDeleteWarning.assert_not_called()

    def test_confirmation_that_starts_an_operation_prevents_deletion(self):
        def confirm(_message):
            self.frame.current_op = object()
            return True

        self.frame._CheckDeleteWarning.side_effect = confirm
        self.frame.OnDelPreset(None)
        self.assertTrue((self.directory / "Alpha.pt").exists())

    def test_delete_all_rechecks_operation_state_after_confirmation(self):
        def confirm(_message):
            self.frame.rec_data = [b"Synthetic pending recording"]
            return True

        self.frame._CheckDeleteWarning.side_effect = confirm
        self.frame.OnDelAllPresets(None)
        self.assertEqual(len(list(self.directory.glob("*.pt"))), 2)

    def test_clone_selection_rejects_link_changed_after_confirmation(self):
        self.assertTrue(hasattr(self.frame, "OnClonePresetKeyDown"))
        actual = safe_child_path

        def validate(directory, name, **kwargs):
            if self.frame._CheckDeleteWarning.called:
                raise ValueError("Synthetic link appeared during confirmation")
            return actual(directory, name, **kwargs)

        with patch.dict(self.namespace, safe_child_path=validate):
            self.frame.OnClonePresetKeyDown(self.key())
        self.assertTrue((self.directory / "Bravo.pt").exists())
        self.wx.MessageBox.assert_called_once()

    def test_failed_clone_delete_reports_error_and_refreshes_both_lists(self):
        self.assertTrue(hasattr(self.frame, "OnClonePresetKeyDown"))
        with patch.object(Path, "unlink", side_effect=PermissionError("Synthetic locked file")):
            self.frame.OnClonePresetKeyDown(self.key())
        self.assertEqual(self.frame.combo_presets.GetClientData(2), "Bravo.pt")
        self.assertEqual(self.frame.list_presets.GetClientData(0), "Alpha.pt")
        self.wx.MessageBox.assert_called_once()

    def test_save_button_handler_always_uses_clone_reference_and_transcript(self):
        frame = SimpleNamespace(
            clone_ref_audio=SimpleNamespace(GetValue=lambda: " synthetic.wav "),
            clone_ref_text=SimpleNamespace(GetValue=lambda: " Synthetic transcript. "),
            _PromptAndSavePreset=Mock(),
        )
        load_handler("OnSavePresetPrompt", {})(frame, None)
        frame._PromptAndSavePreset.assert_called_once_with("synthetic.wav", "Synthetic transcript.")

    def test_save_shortcut_selects_clone_tab_and_uses_same_handler(self):
        frame = SimpleNamespace(
            notebook=SimpleNamespace(SetSelection=Mock()),
            btn_save_preset=SimpleNamespace(IsEnabled=lambda: True),
            OnSavePresetPrompt=Mock(),
        )
        load_handler("OnShortcutSavePreset", self.namespace)(frame, None)
        frame.notebook.SetSelection.assert_called_once_with(0)
        frame.OnSavePresetPrompt.assert_called_once_with(None)

    def test_busy_save_and_edit_do_not_open_dialogs_or_read_preset(self):
        self.frame.current_op = object()
        for name in ("_PromptAndSavePreset", "OnEditPreset"):
            with self.subTest(handler=name):
                handler = load_handler(name, self.namespace)
                if name == "_PromptAndSavePreset":
                    handler(self.frame, "synthetic.wav", "Synthetic transcript.")
                else:
                    handler(self.frame, None)
        self.wx.MessageBox.assert_not_called()

    def test_save_rechecks_operation_state_after_name_and_overwrite_dialogs(self):
        self.wx.ID_OK = 3
        dialog = Mock()
        dialog.GetValue.return_value = "Saved voice"
        self.wx.TextEntryDialog = Mock(return_value=dialog)
        source = self.directory / "reference.wav"
        source.write_bytes(b"Synthetic reference audio; decoding mocked")
        self.frame._CanUseModel = Mock(return_value=True)
        self.frame._ConfirmPresetOverwrite = Mock(return_value=True)
        self.frame._StartPresetRebuild = Mock()
        handler = load_handler(
            "_PromptAndSavePreset",
            dict(
                self.namespace,
                normalize_pasted_path=normalize_pasted_path,
                preset_filename=preset_filename,
            ),
        )

        for phase in ("name", "overwrite"):
            with self.subTest(phase=phase):
                self.frame.current_op = None
                dialog.reset_mock()
                dialog.GetValue.return_value = "Saved voice"
                self.frame._ConfirmPresetOverwrite.reset_mock()

                def confirm_name(phase=phase):
                    if phase == "name":
                        self.frame.current_op = object()
                    return self.wx.ID_OK

                def confirm_overwrite(_path):
                    self.frame.current_op = object()
                    return True

                dialog.ShowModal.side_effect = confirm_name
                self.frame._ConfirmPresetOverwrite.side_effect = confirm_overwrite
                handler(self.frame, str(source), "Synthetic transcript.")
                self.frame._StartPresetRebuild.assert_not_called()
                if phase == "name":
                    self.frame._ConfirmPresetOverwrite.assert_not_called()
                else:
                    self.frame._ConfirmPresetOverwrite.assert_called_once()
                dialog.Destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
