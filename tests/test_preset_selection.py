"""Regression coverage for preset identity and saved display preferences."""

import ast
import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from omnisonic.validation import safe_child_path


ROOT = Path(__file__).resolve().parents[1]


def load_handler(name, namespace):
    tree = ast.parse((ROOT / "omnisonic/app.py").read_text(encoding="utf-8"))
    frame = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "OmniVoiceFrame"
    )
    handler = next(
        node for node in frame.body if isinstance(node, ast.FunctionDef) and node.name == name
    )
    exec(compile(ast.Module(body=[handler], type_ignores=[]), "preset-handler", "exec"), namespace)
    return namespace[name]


class PresetControl:
    def __init__(self):
        self.items = []
        self.selection = -1

    def Clear(self):
        self.items.clear()
        self.selection = -1

    def Append(self, label, data):
        self.items.append((label, data))

    def GetSelection(self):
        return self.selection

    def SetSelection(self, index):
        self.selection = index

    def GetClientData(self, index):
        return self.items[index][1]

    def GetCount(self):
        return len(self.items)


class PresetRefreshTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="omnisonic-preset-selection-")
        self.addCleanup(temporary.cleanup)
        temporary_path = Path(temporary.name)
        # Exercise canonicalization even when Windows does not use a short-name alias.
        self.directory = temporary_path / ".." / temporary_path.name
        for name in ("Alpha.pt", "Bravo.pt"):
            (self.directory / name).touch()
        self.frame = SimpleNamespace(
            combo_presets=PresetControl(),
            list_presets=PresetControl(),
            cfg={"preset_display_mode": "name"},
            current_op=None,
            _=lambda key: key,
            _set_operation_controls_enabled=Mock(),
        )
        refresh = load_handler(
            "RefreshPresets",
            {
                "wx": SimpleNamespace(NOT_FOUND=-1),
                "PRESETS_DIR": self.directory,
                "safe_child_path": safe_child_path,
                "os": os,
                "logging": logging,
            },
        )
        self.frame.RefreshPresets = refresh.__get__(self.frame)
        self.frame.RefreshPresets()
        self.frame.combo_presets.SetSelection(2)
        self.frame.list_presets.SetSelection(1)

    def selected(self):
        return self.frame.combo_presets.GetClientData(self.frame.combo_presets.GetSelection())

    def test_refresh_keeps_active_preset_and_manager_selection(self):
        self.frame.RefreshPresets()
        self.assertEqual(self.selected(), "Bravo.pt")
        managed = self.frame.list_presets
        self.assertEqual(managed.GetClientData(managed.GetSelection()), "Bravo.pt")

    def test_adding_or_removing_another_preset_keeps_active_identity(self):
        (self.directory / "Aardvark.pt").touch()
        self.frame.RefreshPresets()
        self.assertEqual(self.selected(), "Bravo.pt")
        (self.directory / "Alpha.pt").unlink()
        self.frame.RefreshPresets()
        self.assertEqual(self.selected(), "Bravo.pt")

    def test_removed_active_preset_falls_back_to_new_audio(self):
        (self.directory / "Bravo.pt").unlink()
        self.frame.RefreshPresets()
        self.assertEqual(self.frame.combo_presets.GetSelection(), 0)
        self.assertIsNone(self.selected())

    def test_display_change_updates_labels_without_changing_preset(self):
        self.frame.cfg["preset_display_mode"] = "path"
        self.frame.RefreshPresets()
        self.assertEqual(self.selected(), "Bravo.pt")
        self.assertEqual(
            self.frame.combo_presets.items[2][0], str((self.directory / "Bravo.pt").resolve())
        )


class PresetDisplaySettingsTests(unittest.TestCase):
    def test_labels_refresh_only_after_successfully_saving_a_changed_mode(self):
        for changed, accepted, save_error in (
            (True, True, None),
            (False, True, None),
            (True, False, None),
            (True, True, OSError("Cannot save settings")),
        ):
            with self.subTest(changed=changed, accepted=accepted, save_error=save_error):
                original = {
                    "language": "en",
                    "generated_audio_directory": "generated",
                    "preset_display_mode": "name",
                }
                updated = dict(original, preset_display_mode="path" if changed else "name")
                frame = Mock(cfg=original, model=None)
                dialog = Mock(cfg=updated)
                dialog.ShowModal.return_value = 1 if accepted else 0
                handler = load_handler(
                    "OnOpenSettings",
                    {
                        "SettingsDialog": Mock(return_value=dialog),
                        "SaveBasicConfig": Mock(side_effect=save_error),
                        "wx": SimpleNamespace(ID_OK=1, OK=2, ICON_ERROR=4, MessageBox=Mock()),
                    },
                )
                handler(frame, None)
                if accepted and save_error is not None:
                    dialog._restore_parent_ai_state.assert_called_once_with()
                    self.assertIs(frame.cfg, original)
                else:
                    dialog._restore_parent_ai_state.assert_not_called()
                if changed and accepted and save_error is None:
                    frame.RefreshPresets.assert_called_once_with()
                else:
                    frame.RefreshPresets.assert_not_called()


if __name__ == "__main__":
    unittest.main()
