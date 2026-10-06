"""Keyboard capture, remembered generation preferences, and localized file input."""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from omnisonic.config import DEFAULT_CONFIG
from omnisonic.i18n import load_locales, translate
from omnisonic.shortcuts import normalize_shortcut
from omnisonic.validation import (
    FilenameValidationError,
    preset_filename,
    safe_child_path,
    validate_filename_component,
    validation_error_message,
)

ROOT = Path(__file__).resolve().parents[1]


def load_functions(names, namespace):
    tree = ast.parse((ROOT / "omnisonic/app.py").read_text(encoding="utf-8"))
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in names
        or isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_AUDIO_FILE_WILDCARD"
            for target in node.targets
        )
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "ui-preferences", "exec"), namespace)
    return namespace


class ShortcutCaptureTests(unittest.TestCase):
    def test_special_keys_are_not_reinterpreted_as_control_characters(self):
        capture = load_functions(
            {"_shortcut_from_key_event"},
            {
                "wx": SimpleNamespace(WXK_F1=340, WXK_F24=363),
                "normalize_shortcut": normalize_shortcut,
                "_SHORTCUT_WX_KEYS_REVERSED": {
                    8: "Backspace",
                    9: "Tab",
                    13: "Enter",
                    27: "Escape",
                    32: "Space",
                },
            },
        )["_shortcut_from_key_event"]
        for code, name in ((8, "Backspace"), (9, "Tab"), (13, "Enter"), (27, "Escape")):
            for shift in (False, True):
                with self.subTest(code=code, shift=shift):
                    event = SimpleNamespace(
                        GetKeyCode=lambda code=code: code,
                        ControlDown=lambda: True,
                        AltDown=lambda: False,
                        ShiftDown=lambda shift=shift: shift,
                    )
                    self.assertEqual(capture(event), ("Ctrl+Shift+" if shift else "Ctrl+") + name)
        for code in (1, ord("A")):
            event = SimpleNamespace(
                GetKeyCode=lambda code=code: code,
                ControlDown=lambda: True,
                AltDown=lambda: False,
                ShiftDown=lambda: False,
            )
            self.assertEqual(capture(event), "Ctrl+A")


class FileInputLocaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.locales = load_locales((ROOT / "langs",))

    def test_audio_filters_translate_labels_without_changing_extensions(self):
        wildcard = load_functions({"_audio_file_wildcard"}, {})["_audio_file_wildcard"]
        filters = {}
        for language, expected in (("en", "Audio files"), ("pl", "Pliki audio")):
            filters[language] = wildcard(
                lambda key, language=language: translate(self.locales, language, key)
            )
            self.assertTrue(filters[language].startswith(expected))
            self.assertEqual(len(filters[language].split("|")), 4)
            for extension in ("*.wav", "*.flac", "*.ogg", "*.opus", "*.mp3", "*.aiff", "*.caf"):
                self.assertIn(extension, filters[language])
        self.assertEqual(filters["en"].split("|")[1::2], filters["pl"].split("|")[1::2])
        self.assertIn("Wszystkie pliki", filters["pl"])

    def test_filename_errors_keep_valueerror_compatibility_and_translate_the_reason(self):
        invalid = (
            ("", "filename_empty"),
            ("bad?.wav", "filename_invalid_characters"),
            ("name.", "filename_invalid_ending"),
            ("a" * 81, "filename_too_long"),
            ("CON", "filename_reserved"),
        )
        for value, key in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                validate_filename_component(value, label="audio prefix")
            self.assertIsInstance(caught.exception, FilenameValidationError)
            self.assertTrue(str(caught.exception).startswith("audio prefix"))
            for language in ("en", "pl"):
                message = validation_error_message(
                    caught.exception,
                    lambda entry, language=language: translate(self.locales, language, entry),
                )
                self.assertEqual(message, self.locales[language][key])

    def test_preset_and_path_validation_remain_safe_and_localizable(self):
        with self.assertRaises(FilenameValidationError) as caught:
            preset_filename("CON.pt")
        self.assertEqual(caught.exception.message_key, "filename_reserved")
        with self.assertRaises(FilenameValidationError) as caught:
            safe_child_path(ROOT, "../outside.pt")
        self.assertEqual(caught.exception.message_key, "filename_outside_directory")
        self.assertIn(caught.exception.message_key, self.locales["pl"])
        self.assertEqual(preset_filename("Voice.pt"), "Voice.pt")
        self.assertEqual(safe_child_path(ROOT, "Voice.pt"), ROOT / "Voice.pt")

    def test_unrelated_errors_keep_their_original_details(self):
        self.assertEqual(
            validation_error_message(OSError("disk full"), lambda key: key), "disk full"
        )


class DurationPreferenceTests(unittest.TestCase):
    def test_duration_controls_follow_the_same_remember_flag_as_other_generation_settings(self):
        tree = ast.parse((ROOT / "omnisonic/app.py").read_text(encoding="utf-8"))
        frame = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "OmniVoiceFrame"
        )
        handler = next(
            node
            for node in frame.body
            if isinstance(node, ast.FunctionDef) and node.name == "SetupAdvTab"
        )
        namespace = {"wx": MagicMock(), "AccessibleFloatCtrl": MagicMock()}
        exec(
            compile(ast.Module(body=[handler], type_ignores=[]), "duration-preference", "exec"),
            namespace,
        )
        for remember in (False, True):
            with self.subTest(remember=remember):
                namespace["wx"].reset_mock()
                view = SimpleNamespace(
                    cfg=dict(
                        DEFAULT_CONFIG,
                        remember_ai_settings=remember,
                        use_duration=True,
                        duration_val=37.0,
                    ),
                    _=lambda key: key,
                )
                namespace["SetupAdvTab"](view, MagicMock())
                view.chk_duration.SetValue.assert_called_with(remember)
                self.assertEqual(
                    namespace["wx"].SpinCtrlDouble.call_args.kwargs["value"],
                    "37.0" if remember else "5.0",
                )


class WxPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import wx
        except ImportError as error:
            raise unittest.SkipTest("wxPython is not installed") from error
        import wx.lib.scrolledpanel as scrolled

        import omnisonic.app as desktop

        cls.wx = wx
        cls.scrolled = scrolled
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

    def test_real_duration_controls_reset_only_when_remembering_is_disabled(self):
        frame = self.wx.Frame(None)
        try:
            for remember in (False, True):
                with self.subTest(remember=remember):
                    panel = self.scrolled.ScrolledPanel(frame)
                    view = SimpleNamespace(
                        cfg=dict(
                            DEFAULT_CONFIG,
                            remember_ai_settings=remember,
                            use_duration=True,
                            duration_val=37.0,
                        ),
                        _=lambda key: key,
                    )
                    self.desktop.OmniVoiceFrame.SetupAdvTab(view, panel)
                    self.assertEqual(view.chk_duration.GetValue(), remember)
                    self.assertEqual(view.spin_duration.GetValue(), 37.0 if remember else 5.0)
                    self.assertEqual(view.spin_duration.GetName(), "duration_lbl")
        finally:
            frame.Destroy()
            self.application.Yield()

    def test_real_numeric_controls_preserve_minimum_and_zero_guidance(self):
        frame = self.wx.Frame(None)
        try:
            control = self.desktop.AccessibleFloatCtrl(
                frame, value=0.001, min_val=0.001, max_val=10.0, inc=0.01
            )
            control.Increment(-0.01)
            self.assertEqual(self.wx.TextCtrl.GetValue(control), "0.001")
            control.Increment(0.01)
            self.assertEqual(control.GetValue(), 0.011)
            self.assertEqual(self.wx.TextCtrl.GetValue(control), "0.011")
            panel = self.scrolled.ScrolledPanel(frame)
            view = SimpleNamespace(cfg=dict(DEFAULT_CONFIG, ai_cfg=0.0), _=lambda key: key)
            self.desktop.OmniVoiceFrame.SetupAdvTab(view, panel)
            self.assertEqual(view.spin_cfg.GetValue(), 0.0)
        finally:
            frame.Destroy()
            self.application.Yield()

    def test_real_polish_settings_reports_localized_invalid_prefix(self):
        settings = self.desktop.SettingsDialog(
            None, current_cfg=dict(DEFAULT_CONFIG, language="pl")
        )
        try:
            settings.txt_pref_gen.ChangeValue("bad?.wav")
            with patch.object(self.wx, "MessageBox", return_value=self.wx.OK) as message:
                settings.OnSave(None)
            self.assertIn(settings._("filename_invalid_characters"), message.call_args.args[0])
            self.assertNotIn("not allowed", message.call_args.args[0])
        finally:
            settings.Destroy()
            self.application.Yield()

    def test_both_audio_pickers_use_localized_descriptions(self):
        def translator(key):
            return self.desktop.translate(self.desktop.LOCALE, "pl", key)

        editor = self.desktop.PresetEditDialog(None, translator, "Voice", "Reference")
        try:
            with patch.object(self.wx, "FileDialog") as dialog:
                dialog.return_value.__enter__.return_value.ShowModal.return_value = (
                    self.wx.ID_CANCEL
                )
                editor.OnBrowse(None)
                self.desktop.OmniVoiceFrame.BrowseFor(SimpleNamespace(_=translator), MagicMock())
            self.assertEqual(dialog.call_count, 2)
            for call in dialog.call_args_list:
                self.assertIn("Pliki audio", call.kwargs["wildcard"])
                self.assertIn("Wszystkie pliki", call.kwargs["wildcard"])
        finally:
            editor.Destroy()
            self.application.Yield()


if __name__ == "__main__":
    unittest.main()
