"""Corrupt preferences and keyboard/reference-editing boundary regressions."""

from __future__ import annotations

import json
import os
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import omnisonic.config as config
from omnisonic.i18n import FALLBACK_ENGLISH, load_locales
from omnisonic.validation import (
    normalize_pasted_path,
    preset_filename,
    safe_child_path,
    validation_error_message,
)
from tests.materials import scratch_directory
from tests.test_preset_selection import load_handler


class CorruptPreferenceTests(unittest.TestCase):
    @staticmethod
    def nested_json():
        return '{"unknown":' + "[" * 10000 + "0" + "]" * 10000 + "}"

    def test_excessive_json_nesting_uses_config_corruption_fallback(self):
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "read_text", return_value=self.nested_json()),
            self.assertLogs("omnisonic.config", "WARNING"),
        ):
            result = config.load_config("synthetic-settings.json")
        self.assertEqual(result, config.DEFAULT_CONFIG)

    def test_excessive_json_nesting_skips_only_the_broken_locale(self):
        with (
            patch.object(Path, "is_dir", return_value=True),
            patch.object(Path, "glob", return_value=[Path("broken.lng"), Path("pl.lng")]),
            patch.object(
                Path,
                "read_text",
                side_effect=[self.nested_json(), json.dumps({"title": "Synthetic title"})],
            ),
            self.assertLogs("omnisonic.i18n", "WARNING"),
        ):
            locales = load_locales((Path("synthetic-locales"),))
        self.assertNotIn("broken", locales)
        self.assertEqual(locales["pl"], {"title": "Synthetic title"})
        self.assertEqual(locales["en"], FALLBACK_ENGLISH)

    def test_excessive_legacy_json_nesting_allows_portable_settings_recovery(self):
        root = scratch_directory("preferences-corrupt-migration-")
        legacy = root / "legacy"
        program = root / "program"
        legacy.mkdir()
        program.mkdir()
        (legacy / "settings.json").write_text(self.nested_json(), encoding="utf-8")
        (program / "settings.json").write_text('{"font_size": 17}', encoding="utf-8")
        with (
            patch.multiple(
                config,
                PROGRAM_DIR=program,
                PROJECT_ROOT=program,
                APP_DATA_DIR=program / "config",
                CONFIG_FILE=program / "config/settings.json",
                TEMP_DIR=program / "config/temp",
                PRESETS_DIR=program / "presets",
            ),
            patch.object(config, "_legacy_profile_dir", return_value=legacy),
            self.assertLogs("omnisonic.config", "WARNING"),
        ):
            config.migrate_legacy_user_data()
            self.assertEqual(config.load_config(config.CONFIG_FILE)["font_size"], 17)
        self.assertEqual((legacy / "settings.json").read_text(), self.nested_json())


class ProgramDirectoryTests(unittest.TestCase):
    def test_unknown_global_installation_never_uses_the_working_directory(self):
        root = scratch_directory("preferences-program-path-")
        with (
            patch.object(config, "PROJECT_ROOT", root / "unmarked-source"),
            patch.object(config.sys, "prefix", str(root / "system-python")),
            patch.object(config.sys, "base_prefix", str(root / "system-python")),
            patch.object(config.sys, "frozen", False, create=True),
            patch.dict(config.os.environ, {"OMNISONIC_APP_DIR": ""}),
            patch.object(Path, "cwd", return_value=root / "unrelated-working-folder"),
        ):
            with self.assertRaisesRegex(OSError, "start_desktop.bat.*OMNISONIC_APP_DIR"):
                config._program_dir()
        self.assertEqual(list(root.iterdir()), [])

    def test_explicit_frozen_source_and_virtualenv_program_directories_are_unchanged(self):
        root = scratch_directory("preferences-program-path-")
        source = root / "source"
        source.mkdir()
        (source / "start_desktop.bat").write_text("@rem synthetic source marker", encoding="utf-8")
        with (
            patch.object(config, "PROJECT_ROOT", root / "unmarked-source"),
            patch.object(config.sys, "prefix", str(root / "system-python")),
            patch.object(config.sys, "base_prefix", str(root / "system-python")),
            patch.object(config.sys, "frozen", False, create=True),
            patch.dict(config.os.environ, {"OMNISONIC_APP_DIR": ""}),
        ):
            with patch.dict(config.os.environ, {"OMNISONIC_APP_DIR": str(root / "explicit")}):
                self.assertEqual(config._program_dir(), (root / "explicit").resolve())
            with (
                patch.object(config.sys, "frozen", True),
                patch.object(config.sys, "executable", str(root / "frozen/omnisonic.exe")),
            ):
                self.assertEqual(config._program_dir(), (root / "frozen").resolve())
            with patch.object(config, "PROJECT_ROOT", source):
                self.assertEqual(config._program_dir(), source)
            with patch.object(config.sys, "prefix", str(root / "application/env")):
                self.assertEqual(config._program_dir(), (root / "application").resolve())


class WxPreferenceEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import wx
        except ImportError as error:
            raise unittest.SkipTest("wxPython is not installed") from error
        import omnisonic.app as desktop

        cls.wx = wx
        cls.desktop = desktop
        cls.application = wx.GetApp()
        cls.owns_application = cls.application is None
        if cls.owns_application:
            cls.application = wx.App(False)

    @classmethod
    def tearDownClass(cls):
        cls.application.Yield()
        if cls.owns_application:
            cls.application.Destroy()

    def test_preset_editor_has_save_as_default_and_standard_escape(self):
        editor = self.desktop.PresetEditDialog(None, lambda key: key, "Voice", "Synthetic")
        try:
            default = editor.GetDefaultItem()
            self.assertIsNotNone(default)
            self.assertEqual(default.GetId(), self.wx.ID_OK)
            self.assertEqual(editor.GetAffirmativeId(), self.wx.ID_OK)
            self.assertEqual(editor.GetEscapeId(), self.wx.ID_CANCEL)
            self.assertEqual(editor.name_ctrl.GetName(), "preset_edit_name")
        finally:
            editor.Destroy()
            self.application.Yield()

    def test_managed_source_change_invalidates_the_previous_reference_text(self):
        frame = self.wx.Frame(None)
        panel = self.wx.Panel(frame)
        view = SimpleNamespace(_=lambda key: key)
        for name in (
            "OnPresetManagerKeyDown",
            "OnEditPreset",
            "RefreshPresets",
            "OnDelPreset",
            "OnDelAllPresets",
            "BrowseFor",
            "OnSaveManagedPreset",
        ):
            setattr(view, name, Mock())
        view.OnPresetSourceChanged = lambda event: (
            self.desktop.OmniVoiceFrame.OnPresetSourceChanged(view, event)
        )
        try:
            self.desktop.OmniVoiceFrame.SetupPresetsTab(view, panel)
            view.preset_source_audio.SetValue("synthetic-first.wav")
            view.preset_source_ref_text.SetValue("Transcript of first source")
            view.preset_source_audio.SetValue("synthetic-second.wav")
            self.application.Yield()
            self.assertEqual(view.preset_source_ref_text.GetValue(), "")
            self.assertEqual(view.preset_source_ref_text.GetName(), "preset_source_ref_text")
        finally:
            frame.Destroy()
            self.application.Yield()

    def test_invalid_shortcut_capture_updates_its_accessible_status_name(self):
        dialog = self.desktop.ShortcutCaptureDialog(None, lambda key: key)
        try:
            event = SimpleNamespace(
                GetKeyCode=lambda: ord("G"),
                ControlDown=lambda: False,
                AltDown=lambda: False,
                ShiftDown=lambda: False,
            )
            dialog.OnKey(event)
            self.assertEqual(dialog.instructions.GetLabel(), "shortcut_capture_invalid")
            self.assertEqual(dialog.instructions.GetName(), "shortcut_capture_invalid")
        finally:
            dialog.Destroy()
            self.application.Yield()

    def test_unsaved_reset_does_not_mutate_the_callers_configuration(self):
        settings_config = deepcopy(config.DEFAULT_CONFIG)
        settings_config["font_size"] = 17
        dialog = self.desktop.SettingsDialog(None, current_cfg=settings_config)
        try:
            with patch.object(self.wx, "MessageBox", return_value=self.wx.YES):
                dialog.OnResetApp(None)
            self.assertEqual(settings_config["font_size"], 17)
        finally:
            dialog.Destroy()
            self.application.Yield()

    def test_application_reset_updates_language_controls_and_cancel_restores_them(self):
        parent = self.wx.Frame(None)
        for name, value in (
            ("spin_steps", 29),
            ("spin_seed", 42),
        ):
            setattr(parent, name, self.wx.SpinCtrl(parent, min=0, max=100, initial=value))
        for name in (
            "spin_cfg",
            "spin_speed",
            "spin_t_shift",
            "spin_layer_penalty",
            "spin_position_temperature",
            "spin_class_temperature",
            "spin_chunk_duration",
            "spin_chunk_threshold",
            "spin_pad_duration",
            "spin_fade_duration",
        ):
            setattr(
                parent,
                name,
                self.desktop.AccessibleFloatCtrl(parent, 0.25, 0, 100, 0.1),
            )
        for name in (
            "chk_seed",
            "chk_denoise",
            "chk_preprocess_prompt",
            "chk_postprocess_output",
            "chk_duration",
        ):
            setattr(parent, name, self.wx.CheckBox(parent))
        parent.clone_instruct = self.wx.TextCtrl(parent, value="Original clone instruction")
        parent.design_custom_instruct = self.wx.TextCtrl(
            parent, value="Original design instruction"
        )
        parent.spin_duration = self.wx.SpinCtrlDouble(parent, min=0.1, max=100, initial=7)
        previous = {"clone_lang": "Polish", "design_lang": "English", "auto_lang": "Polish"}
        for name, value in previous.items():
            control = self.wx.ComboBox(
                parent, choices=["Auto", "English", "Polish"], style=self.wx.CB_READONLY
            )
            control.SetValue(value)
            setattr(parent, name, control)
        dialog = self.desktop.SettingsDialog(
            parent, current_cfg=dict(config.DEFAULT_CONFIG, **previous)
        )
        try:
            with patch.object(self.wx, "MessageBox", return_value=self.wx.YES):
                dialog.OnResetApp(None)
            for name in previous:
                self.assertEqual(getattr(parent, name).GetValue(), "Auto")
                self.assertEqual(dialog.cfg[name], "Auto")
            dialog._restore_parent_ai_state()
            for name, value in previous.items():
                self.assertEqual(getattr(parent, name).GetValue(), value)
        finally:
            dialog.Destroy()
            parent.Destroy()
            self.application.Yield()


class PresetSourcePathTests(unittest.TestCase):
    def test_copy_as_path_wrapper_is_removed_before_checking_and_saving_a_preset(self):
        directory = scratch_directory("preset-copy-as-path-")
        source = directory / "synthetic narrator's source.wav"
        source.write_bytes(b"synthetic audio; decoding is mocked")
        wx = MagicMock(ID_OK=1)
        wx.TextEntryDialog.return_value.ShowModal.return_value = wx.ID_OK
        wx.TextEntryDialog.return_value.GetValue.return_value = "Synthetic preset"
        view = Mock()
        view._.side_effect = lambda key: key
        view._CanUseModel.return_value = True
        view._ConfirmPresetOverwrite.return_value = True
        handler = load_handler(
            "_PromptAndSavePreset",
            dict(
                wx=wx,
                os=os,
                normalize_pasted_path=normalize_pasted_path,
                preset_filename=preset_filename,
                safe_child_path=safe_child_path,
                PRESETS_DIR=directory,
                validation_error_message=validation_error_message,
            ),
        )
        handler(view, f'"{source}"', "Synthetic reference transcript")
        view._StartPresetRebuild.assert_called_once_with(
            str(source), "Synthetic reference transcript", directory / "Synthetic preset.pt"
        )
        wx.MessageBox.assert_not_called()


if __name__ == "__main__":
    unittest.main()
