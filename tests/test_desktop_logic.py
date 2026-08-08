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
    load_config,
    normalize_config,
    save_config,
)
from omnisonic.i18n import load_locales, missing_keys, translate
from omnisonic.operations import OperationState, execute_worker
from omnisonic.validation import (
    preset_filename,
    safe_child_path,
    validate_filename_component,
)


class ConfigTests(unittest.TestCase):
    def test_presets_are_portable_and_live_next_to_the_program(self):
        self.assertEqual(PRESETS_DIR, PROJECT_ROOT / "presets")

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
            self.assertEqual(safe_child_path(root, "voice.pt"), root / "voice.pt")
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


if __name__ == "__main__":
    unittest.main()
