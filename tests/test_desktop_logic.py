from __future__ import annotations

import ast
import json
import string
import tempfile
import unittest
from pathlib import Path

from omnisonic.config import (
    DEFAULT_CONFIG,
    PRESETS_DIR,
    PROJECT_ROOT,
    default_audio_directory,
    load_config,
    normalize_config,
    save_config,
)
from omnisonic.i18n import load_locales, missing_keys, translate
from omnisonic.operations import OperationState, execute_worker
from omnisonic.shortcuts import (
    SHORTCUT_DEFINITIONS,
    find_shortcut_conflicts,
    normalize_shortcut,
)
from omnisonic.validation import (
    preset_filename,
    safe_child_path,
    validate_filename_component,
)


class ConfigTests(unittest.TestCase):
    def test_presets_are_portable_and_live_next_to_the_program(self):
        self.assertEqual(PRESETS_DIR, PROJECT_ROOT / "presets")

    def test_audio_output_directories_have_expected_defaults(self):
        self.assertEqual(
            DEFAULT_CONFIG["generated_audio_directory"],
            str(default_audio_directory("generated")),
        )
        self.assertEqual(
            DEFAULT_CONFIG["recorded_audio_directory"],
            str(default_audio_directory("record")),
        )
        self.assertEqual(Path(DEFAULT_CONFIG["generated_audio_directory"]).name, "generated")
        self.assertEqual(Path(DEFAULT_CONFIG["recorded_audio_directory"]).name, "record")

    def test_invalid_audio_output_directories_fall_back_to_defaults(self):
        result = normalize_config(
            {
                "generated_audio_directory": None,
                "recorded_audio_directory": "   ",
            }
        )
        self.assertEqual(
            result["generated_audio_directory"], DEFAULT_CONFIG["generated_audio_directory"]
        )
        self.assertEqual(
            result["recorded_audio_directory"], DEFAULT_CONFIG["recorded_audio_directory"]
        )

    def test_normalize_config_repairs_invalid_values(self):
        result = normalize_config(
            {
                "font_size": 999,
                "ai_steps": "bad",
                "theme": "unknown",
                "show_progress": "yes",
                "obsolete_option": True,
            }
        )
        self.assertEqual(result["font_size"], 24)
        self.assertEqual(result["ai_steps"], DEFAULT_CONFIG["ai_steps"])
        self.assertEqual(result["theme"], "light")
        self.assertIs(result["show_progress"], DEFAULT_CONFIG["show_progress"])
        self.assertNotIn("obsolete_option", result)

    def test_normalize_config_repairs_full_generation_settings(self):
        result = normalize_config(
            {
                "ai_t_shift": 0,
                "ai_layer_penalty_factor": -1,
                "ai_position_temperature": 1000,
                "ai_class_temperature": "bad",
                "ai_audio_chunk_duration": -5,
                "ai_audio_chunk_threshold": 9999,
                "ai_pad_duration": -1,
                "ai_fade_duration": 99,
                "ai_preprocess_prompt": "yes",
                "ai_postprocess_output": None,
                "clone_instruct": 123,
                "design_instruct": ["whisper"],
            }
        )
        self.assertEqual(result["ai_t_shift"], 0.001)
        self.assertEqual(result["ai_layer_penalty_factor"], 0.0)
        self.assertEqual(result["ai_position_temperature"], 100.0)
        self.assertEqual(result["ai_class_temperature"], 0.0)
        self.assertEqual(result["ai_audio_chunk_duration"], 0.0)
        self.assertEqual(result["ai_audio_chunk_threshold"], 3600.0)
        self.assertEqual(result["ai_pad_duration"], 0.0)
        self.assertEqual(result["ai_fade_duration"], 10.0)
        self.assertTrue(result["ai_preprocess_prompt"])
        self.assertTrue(result["ai_postprocess_output"])
        self.assertEqual(result["clone_instruct"], "")
        self.assertEqual(result["design_instruct"], "")

    def test_config_round_trip_is_valid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            save_config({"language": "pl", "ai_cfg": 3.5}, path)
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["language"], "pl")
            self.assertEqual(load_config(path)["ai_cfg"], 3.5)

    def test_broken_config_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertLogs("omnisonic.config", level="WARNING"):
                self.assertEqual(load_config(path), DEFAULT_CONFIG)

    def test_shortcut_config_is_normalized_and_unknown_actions_are_removed(self):
        result = normalize_config(
            {
                "shortcut_bindings": {
                    "generate": "control + shift + g",
                    "save_result": "not-a-shortcut",
                    "unknown": "Ctrl+U",
                },
                "shortcut_enabled": {"generate": False, "save_result": "no"},
            }
        )
        self.assertEqual(result["shortcut_bindings"]["generate"], "Ctrl+Shift+G")
        self.assertEqual(result["shortcut_bindings"]["save_result"], "Ctrl+S")
        self.assertNotIn("unknown", result["shortcut_bindings"])
        self.assertFalse(result["shortcut_enabled"]["generate"])
        self.assertTrue(result["shortcut_enabled"]["save_result"])

    def test_default_shortcut_config_is_not_shared_between_loads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.json"
            first = load_config(missing_path)
            second = load_config(missing_path)
        first["shortcut_bindings"]["generate"] = "Ctrl+Alt+G"
        self.assertEqual(second["shortcut_bindings"]["generate"], "Ctrl+G")
        self.assertEqual(DEFAULT_CONFIG["shortcut_bindings"]["generate"], "Ctrl+G")


class ValidationTests(unittest.TestCase):
    def test_preset_name_gets_one_extension(self):
        self.assertEqual(preset_filename("My voice.pt"), "My voice.pt")

    def test_rejects_traversal_and_reserved_names(self):
        for value in ("../voice", "voice/name", "CON", "bad?.wav"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_filename_component(value)

    def test_safe_child_path_cannot_escape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertEqual(safe_child_path(root, "voice.pt"), root.resolve() / "voice.pt")
            with self.assertRaises(ValueError):
                safe_child_path(root, "../outside.pt")


class OperationTests(unittest.TestCase):
    def test_success_result_is_preserved(self):
        state = execute_worker(OperationState("success"), lambda operation: 42)
        self.assertTrue(state.succeeded)
        self.assertEqual(state.result, 42)

    def test_worker_error_is_preserved(self):
        def fail(_operation):
            raise RuntimeError("boom")

        with self.assertLogs("omnisonic.operations", level="ERROR"):
            state = execute_worker(OperationState("failure"), fail)
        self.assertFalse(state.succeeded)
        self.assertIsInstance(state.error, RuntimeError)

    def test_cancelled_worker_cannot_report_success(self):
        state = OperationState("cancel")

        def cancel(operation):
            operation.request_cancel()
            return "stale result"

        execute_worker(state, cancel)
        self.assertFalse(state.succeeded)
        self.assertTrue(state.cancel_flag)


class ShortcutTests(unittest.TestCase):
    def test_shortcuts_are_canonicalized(self):
        self.assertEqual(normalize_shortcut("control + shift + g"), "Ctrl+Shift+G")
        self.assertEqual(normalize_shortcut("alt+f12"), "Alt+F12")
        self.assertEqual(normalize_shortcut("Ctrl + page down"), "Ctrl+PageDown")

    def test_plain_letters_and_unsupported_keys_are_rejected(self):
        for shortcut in ("G", "Shift+G", "Ctrl++G", "Ctrl+VolumeUp"):
            with self.subTest(shortcut=shortcut), self.assertRaises(ValueError):
                normalize_shortcut(shortcut)

    def test_conflicts_only_include_enabled_shortcuts(self):
        bindings = {definition.key: definition.default for definition in SHORTCUT_DEFINITIONS}
        enabled = {definition.key: True for definition in SHORTCUT_DEFINITIONS}
        bindings["save_result"] = bindings["generate"]
        self.assertEqual(
            find_shortcut_conflicts(bindings, enabled),
            [("generate", "save_result", "Ctrl+G")],
        )
        enabled["save_result"] = False
        self.assertEqual(find_shortcut_conflicts(bindings, enabled), [])


class LocaleTests(unittest.TestCase):
    @staticmethod
    def _load_project_locales():
        root = Path(__file__).resolve().parents[1]
        return root, load_locales((root / "langs",))

    def test_project_locales_are_valid_and_complete(self):
        _root, locales = self._load_project_locales()
        self.assertIn("en", locales)
        self.assertIn("pl", locales)
        self.assertEqual(missing_keys(locales)["pl"], set())
        self.assertEqual(translate(locales, "pl", "title"), "OmniSonic")
        self.assertEqual(translate(locales, "pl", "menu_help_tags"), "Lista znaczników głosu")
        self.assertEqual(translate(locales, "en", "menu_help_tags"), "Voice tag list")
        for definition in SHORTCUT_DEFINITIONS:
            with self.subTest(shortcut=definition.key):
                self.assertIn(definition.label_key, locales["en"])
                self.assertIn(definition.label_key, locales["pl"])

    def test_locale_placeholders_and_unicode_are_consistent(self):
        _root, locales = self._load_project_locales()
        formatter = string.Formatter()

        def placeholders(value):
            return {
                field_name
                for _literal, field_name, _format_spec, _conversion in formatter.parse(value)
                if field_name
            }

        for key, english in locales["en"].items():
            with self.subTest(key=key):
                self.assertEqual(placeholders(locales["pl"][key]), placeholders(english))
                self.assertNotIn("\ufffd", locales["pl"][key])

    def test_every_literal_ui_translation_key_exists(self):
        root, locales = self._load_project_locales()
        tree = ast.parse((root / "omnisonic" / "app.py").read_text(encoding="utf-8"))
        used_keys = set()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = getattr(node.func, "attr", getattr(node.func, "id", None))
            if function_name == "_" and node.args and isinstance(node.args[0], ast.Constant):
                used_keys.add(node.args[0].value)
            elif function_name == "translate" and len(node.args) >= 3:
                if isinstance(node.args[2], ast.Constant):
                    used_keys.add(node.args[2].value)
            elif function_name == "RunOperation" and len(node.args) >= 2:
                for argument in node.args[:2]:
                    if isinstance(argument, ast.Constant):
                        used_keys.add(argument.value)

        categories = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_CATEGORIES"
                for target in node.targets
            ):
                categories = ast.literal_eval(node.value)
                break

        used_keys.update(f"cat_{category}" for category in categories)
        used_keys.update(f"val_{value}" for values in categories.values() for value in values)
        self.assertEqual(used_keys - set(locales["en"]), set())


class DesktopSourceTests(unittest.TestCase):
    @staticmethod
    def _app_tree():
        root = Path(__file__).resolve().parents[1]
        source = (root / "omnisonic" / "app.py").read_text(encoding="utf-8")
        return source, ast.parse(source)

    def test_reference_audio_picker_exposes_supported_formats(self):
        _source, tree = self._app_tree()
        wildcard = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "_AUDIO_FILE_WILDCARD"
                for target in node.targets
            ):
                wildcard = ast.literal_eval(node.value).lower()
                break
        self.assertIsNotNone(wildcard)
        for extension in ("*.wav", "*.flac", "*.ogg", "*.opus", "*.mp3", "*.aiff", "*.caf"):
            with self.subTest(extension=extension):
                self.assertIn(extension, wildcard)

    def test_clone_tab_has_no_preset_delete_binding(self):
        _source, tree = self._app_tree()
        frame = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "OmniVoiceFrame"
        )
        clone_setup = next(
            node
            for node in frame.body
            if isinstance(node, ast.FunctionDef) and node.name == "SetupCloneTab"
        )
        called_handlers = {
            argument.attr
            for node in ast.walk(clone_setup)
            if isinstance(node, ast.Call)
            for argument in node.args
            if isinstance(argument, ast.Attribute)
        }
        self.assertNotIn("OnDelPreset", called_handlers)
        self.assertNotIn("OnDelAllPresets", called_handlers)
        self.assertNotIn("OnPresetManagerKeyDown", called_handlers)

    def test_gui_forwards_every_generation_config_field(self):
        _source, tree = self._app_tree()
        frame = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "OmniVoiceFrame"
        )
        get_config = next(
            node
            for node in frame.body
            if isinstance(node, ast.FunctionDef) and node.name == "GetGenConfig"
        )
        constructor = next(
            node
            for node in ast.walk(get_config)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "OmniVoiceGenerationConfig"
        )
        self.assertEqual(
            {keyword.arg for keyword in constructor.keywords},
            {
                "num_step",
                "guidance_scale",
                "t_shift",
                "layer_penalty_factor",
                "position_temperature",
                "class_temperature",
                "denoise",
                "preprocess_prompt",
                "postprocess_output",
                "audio_chunk_duration",
                "audio_chunk_threshold",
                "pad_duration",
                "fade_duration",
            },
        )

    def test_settings_dialog_has_standard_keyboard_buttons(self):
        source, tree = self._app_tree()
        settings = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog"
        )
        init_ui = next(
            node
            for node in settings.body
            if isinstance(node, ast.FunctionDef) and node.name == "InitUI"
        )
        button_ids = {
            ast.unparse(call.args[1])
            for call in ast.walk(init_ui)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "Button"
            and len(call.args) >= 2
        }
        self.assertIn("wx.ID_OK", button_ids)
        self.assertIn("wx.ID_CANCEL", button_ids)
        self.assertIn("self.btn_ok.SetDefault()", source)
        self.assertIn("self.SetEscapeId(wx.ID_CANCEL)", source)

    def test_audio_saving_uses_configured_directories(self):
        _source, tree = self._app_tree()
        frame = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "OmniVoiceFrame"
        )
        save_audio = next(
            node
            for node in frame.body
            if isinstance(node, ast.FunctionDef) and node.name == "PerformSaveAudio"
        )
        constants = {
            node.value
            for node in ast.walk(save_audio)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertIn("generated_audio_directory", constants)
        self.assertIn("recorded_audio_directory", constants)

    def test_settings_cancel_checks_for_unsaved_changes(self):
        _source, tree = self._app_tree()
        settings = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog"
        )
        handle_cancel = next(
            node
            for node in settings.body
            if isinstance(node, ast.FunctionDef) and node.name == "HandleCancel"
        )
        cancel_source = ast.unparse(handle_cancel)
        self.assertIn("self._has_unsaved_changes()", cancel_source)
        self.assertIn("self._restore_parent_ai_state()", cancel_source)
        self.assertIn("self._('discard_settings_confirm')", cancel_source)


if __name__ == "__main__":
    unittest.main()
