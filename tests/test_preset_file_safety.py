"""Cloud-file discovery and preset deletion regressions using synthetic files only."""

import ast
import inspect
import logging
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from omnisonic.batch import discover_text_files, read_text_input
from omnisonic.operations import OperationState
from omnisonic.validation import (
    FilenameValidationError,
    is_path_link,
    preset_filename,
    safe_child_path,
    validation_error_message,
)
from tests.test_file_safety import app_methods
from tests.test_preset_selection import PresetControl, load_handler


ROOT = Path(__file__).resolve().parents[1]


def setUpModule():
    (ROOT / "trash").mkdir(exist_ok=True)


def reparse_info(mode, tag):
    return SimpleNamespace(st_mode=mode, st_file_attributes=0x400, st_reparse_tag=tag)


class ReparseFileTests(unittest.TestCase):
    def test_only_redirecting_or_unknown_reparse_entries_are_rejected(self):
        for mode, tag, expected in (
            (stat.S_IFREG, 0x9000001A, False),
            (stat.S_IFDIR, 0x9000001A, False),
            (stat.S_IFREG, 0x9000701A, False),
            (stat.S_IFLNK, 0xA000000C, True),
            (stat.S_IFDIR, 0xA0000003, True),
            (stat.S_IFREG, 0xA0000100, True),
            (stat.S_IFREG, 0, True),
        ):
            with self.subTest(mode=mode, tag=tag):
                with patch.object(Path, "lstat", return_value=reparse_info(mode, tag)):
                    self.assertEqual(is_path_link(Path("synthetic.txt")), expected)

    def test_cloud_files_and_folders_are_discovered_without_hydrating_real_user_files(self):
        directory = Path(tempfile.mkdtemp(prefix="cloud-discovery-", dir=ROOT / "trash"))
        nested = directory / "cloud-folder"
        nested.mkdir()
        source = nested / "readable.txt"
        source.write_text("Synthetic readable cloud-backed text.", encoding="utf-8")
        original_lstat = Path.lstat

        def cloud_lstat(path):
            info = original_lstat(path)
            return reparse_info(info.st_mode, 0x9000001A)

        with patch.object(Path, "lstat", autospec=True, side_effect=cloud_lstat):
            inputs, errors = discover_text_files([directory])
        self.assertEqual([item.path for item in inputs], [source])
        self.assertEqual(errors, [])
        self.assertEqual(read_text_input(source), "Synthetic readable cloud-backed text.")
        with patch.object(Path, "lstat", return_value=reparse_info(stat.S_IFDIR, 0xA0000003)):
            inputs, errors = discover_text_files([directory])
        self.assertEqual(inputs, [])
        self.assertEqual(errors, [(str(directory), "batch_link_skipped")])


class PresetFileSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="preset-file-safety-", dir=ROOT / "trash"))
        self.wx = MagicMock(NOT_FOUND=-1, ID_YES=1, YES_NO=2, ICON_WARNING=4, OK=8, ICON_ERROR=16)
        self.namespace = {
            "wx": self.wx,
            "PRESETS_DIR": self.directory,
            "safe_child_path": safe_child_path,
            "validation_error_message": validation_error_message,
            "logging": logging,
            "os": os,
            "Path": Path,
        }
        self.frame = SimpleNamespace(
            cfg={"preset_display_mode": "name", "warn_delete_preset": True},
            combo_presets=PresetControl(),
            list_presets=PresetControl(),
            current_op=None,
            _CheckDeleteWarning=Mock(return_value=True),
            _set_operation_controls_enabled=Mock(),
            _=lambda key: key,
        )
        for name in ("RefreshPresets", "_SelectedManagedPreset", "OnDelPreset", "OnDelAllPresets"):
            handler = load_handler(name, self.namespace)
            setattr(self.frame, name, handler.__get__(self.frame))

    def file(self, name):
        path = self.directory / name
        path.write_bytes(b"synthetic preset")
        return path

    def link_metadata(self, alias, original):
        original_resolve, original_lstat = Path.resolve, Path.lstat

        def resolve(path, *args, **kwargs):
            return original if path == alias else original_resolve(path, *args, **kwargs)

        def lstat(path):
            if path == alias:
                return reparse_info(stat.S_IFLNK, 0xA000000C)
            return original_lstat(path)

        return (
            patch.object(Path, "resolve", autospec=True, side_effect=resolve),
            patch.object(Path, "lstat", autospec=True, side_effect=lstat),
        )

    def test_alias_resolution_is_rejected_before_listing_selection_or_deletion(self):
        original = self.file("Original.pt")
        alias = self.file("Alias.pt")
        resolver, attributes = self.link_metadata(alias, original)
        with resolver, attributes:
            self.assertEqual(safe_child_path(self.directory, alias.name), original)
            with self.assertRaises(FilenameValidationError) as caught:
                safe_child_path(self.directory, alias.name, reject_links=True)
            self.assertEqual(caught.exception.message_key, "preset_link_not_allowed")
            with self.assertLogs(level="WARNING"):
                self.frame.RefreshPresets()
            self.assertEqual(self.frame.list_presets.items, [("Original", "Original.pt")])
            self.frame.list_presets.Append("Alias", "Alias.pt")
            self.frame.list_presets.SetSelection(1)
            with patch.object(Path, "unlink", autospec=True) as unlink:
                self.frame.OnDelPreset(None)
            unlink.assert_not_called()
            self.frame._CheckDeleteWarning.assert_not_called()
        self.assertTrue(original.is_file())
        self.assertTrue(alias.is_file())

    def test_preset_write_and_clone_worker_recheck_links_after_selection(self):
        original = self.file("Original.pt")
        alias = self.file("Alias.pt")
        writer = Mock()
        prompt_type = Mock()
        namespace = dict(self.namespace, atomic_write=writer, VoiceClonePrompt=prompt_type)
        handlers = app_methods({"_SavePromptAtomically", "_GenCloneWorker"}, namespace)
        resolver, attributes = self.link_metadata(alias, original)
        with resolver, attributes:
            with self.assertRaises(FilenameValidationError):
                handlers["_SavePromptAtomically"](OperationState(), Mock(), alias)
            worker = handlers["_GenCloneWorker"]
            arguments = {name: None for name in inspect.signature(worker).parameters}
            arguments.update(self=self.frame, state=OperationState(), preset_path=str(alias))
            with self.assertRaises(FilenameValidationError):
                worker(**arguments)
        writer.assert_not_called()
        prompt_type.load.assert_not_called()
        self.assertEqual(original.read_bytes(), b"synthetic preset")

    def test_batch_selection_and_worker_both_enable_link_rejection(self):
        tree = ast.parse((ROOT / "omnisonic/batch_ui.py").read_text(encoding="utf-8"))
        for name in ("OnGenBatch", "_GenBatchWorker"):
            method = next(
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
            calls = [
                node
                for node in ast.walk(method)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "safe_child_path"
            ]
            self.assertTrue(calls, name)
            for call in calls:
                self.assertTrue(
                    any(
                        keyword.arg == "reject_links" and ast.literal_eval(keyword.value) is True
                        for keyword in call.keywords
                    )
                )

    def test_partial_delete_refreshes_lists_and_active_selection(self):
        first, readonly = self.file("A-first.pt"), self.file("B-readonly.pt")
        self.frame.RefreshPresets()
        self.frame.combo_presets.SetSelection(1)
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path == readonly:
                raise PermissionError("synthetic readonly preset")
            self.assertTrue(path.resolve().is_relative_to(self.directory))
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", autospec=True, side_effect=unlink):
            self.frame.OnDelAllPresets(None)
        self.assertFalse(first.exists())
        self.assertTrue(readonly.exists())
        self.assertEqual(self.frame.combo_presets.GetSelection(), 0)
        self.assertEqual(self.frame.list_presets.items, [("B-readonly", "B-readonly.pt")])
        self.wx.MessageBox.assert_called_once()

    def test_delete_all_ignores_directories_and_unsafe_aliases(self):
        original = self.file("Original.pt")
        alias = self.file("Alias.pt")
        directory = self.directory / "Backup.pt"
        directory.mkdir()
        unrelated = self.file("notes.txt")
        resolver, attributes = self.link_metadata(alias, original)
        with resolver, attributes, self.assertLogs(level="WARNING"):
            self.frame.OnDelAllPresets(None)
        self.assertFalse(original.exists())
        self.assertTrue(alias.exists())
        self.assertTrue(directory.is_dir())
        self.assertTrue(unrelated.exists())

    def test_delete_revalidates_a_file_replaced_by_a_link_during_confirmation(self):
        original = self.file("Original.pt")
        candidate = self.file("Selected.pt")
        self.frame._SelectedManagedPreset = Mock(return_value=candidate)
        self.frame.RefreshPresets = Mock()
        resolver, attributes = self.link_metadata(candidate, original)
        with resolver, attributes, patch.object(Path, "unlink", autospec=True) as unlink:
            self.frame.OnDelPreset(None)
        unlink.assert_not_called()
        self.frame.RefreshPresets.assert_called_once()
        self.wx.MessageBox.assert_called_once()

    def test_warning_preference_save_failure_aborts_deletion_and_closes_dialog(self):
        save_config = Mock(side_effect=PermissionError("synthetic read-only settings"))
        handler = load_handler(
            "_CheckDeleteWarning", dict(self.namespace, SaveBasicConfig=save_config)
        )
        self.wx.RichMessageDialog.return_value.ShowModal.return_value = self.wx.ID_YES
        self.wx.RichMessageDialog.return_value.IsCheckBoxChecked.return_value = True
        result = handler(self.frame, "Confirm deletion")
        self.assertFalse(result)
        self.assertTrue(self.frame.cfg["warn_delete_preset"])
        self.wx.RichMessageDialog.return_value.Destroy.assert_called_once()
        self.wx.MessageBox.assert_called_once()

    def test_warning_preference_changes_only_after_successful_persistence(self):
        save_config = Mock()
        handler = load_handler(
            "_CheckDeleteWarning", dict(self.namespace, SaveBasicConfig=save_config)
        )
        self.wx.RichMessageDialog.return_value.ShowModal.return_value = self.wx.ID_YES
        self.wx.RichMessageDialog.return_value.IsCheckBoxChecked.return_value = True
        self.assertTrue(handler(self.frame, "Confirm deletion"))
        self.assertFalse(self.frame.cfg["warn_delete_preset"])
        self.assertFalse(save_config.call_args.args[0]["warn_delete_preset"])
        self.wx.RichMessageDialog.return_value.Destroy.assert_called_once()

    def test_preset_entry_points_report_access_errors_without_starting_work(self):
        source = self.file("synthetic-reference.wav")
        preset = self.file("Selected.pt")
        for method in (
            "_SelectedManagedPreset",
            "_PromptAndSavePreset",
            "OnEditPreset",
            "OnGenClone",
            "OnGenBatch",
        ):
            with self.subTest(method=method):
                self.wx.reset_mock()
                dialog = Mock()
                dialog.ShowModal.return_value = self.wx.ID_OK
                dialog.GetValue.return_value = "New preset"
                dialog.name_ctrl.GetValue.return_value = "New preset"
                self.wx.TextEntryDialog.return_value = dialog
                frame = Mock(cfg={}, batch_items=[SimpleNamespace(status="pending")])
                frame._.side_effect = lambda key: key
                frame._SelectedManagedPreset.return_value = preset
                frame._CanUseModel.return_value = True
                frame.combo_presets.GetSelection.return_value = 1
                frame.combo_presets.GetClientData.return_value = preset.name
                frame.list_presets.GetSelection.return_value = 0
                frame.list_presets.GetClientData.return_value = preset.name
                frame.clone_text.GetValue.return_value = "Synthetic clone text."
                frame.batch_mode.GetSelection.return_value = 0
                namespace = dict(
                    self.namespace,
                    preset_filename=preset_filename,
                    safe_child_path=Mock(side_effect=PermissionError("synthetic denied access")),
                    PresetEditDialog=Mock(return_value=dialog),
                    VoiceClonePrompt=Mock(),
                )
                if method == "OnGenBatch":
                    tree = ast.parse((ROOT / "omnisonic/batch_ui.py").read_text(encoding="utf-8"))
                    node = next(
                        node
                        for node in ast.walk(tree)
                        if isinstance(node, ast.FunctionDef) and node.name == method
                    )
                    exec(
                        compile(ast.Module(body=[node], type_ignores=[]), "batch-handler", "exec"),
                        namespace,
                    )
                    handler = namespace[method]
                else:
                    handler = load_handler(method, namespace)
                arguments = (
                    (str(source), None)
                    if method == "_PromptAndSavePreset"
                    else ()
                    if method == "_SelectedManagedPreset"
                    else (None,)
                )
                handler(frame, *arguments)
                self.wx.MessageBox.assert_called_once()
                frame.RunModelOperation.assert_not_called()
                frame.RunOperation.assert_not_called()
                frame._StartPresetRebuild.assert_not_called()
                if method in {"_PromptAndSavePreset", "OnEditPreset"}:
                    dialog.Destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
