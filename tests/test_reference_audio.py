"""Lightweight ASR invocation and configuration migration regressions."""

import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import omnisonic.config as config


ROOT = Path(__file__).resolve().parents[1]


class ReferenceTests(unittest.TestCase):
    def test_whisper_enables_long_form_for_file_paths_and_arrays(self):
        source = ast.parse((ROOT / "omnivoice/models/omnivoice.py").read_text(encoding="utf-8"))
        method = next(
            node
            for node in ast.walk(source)
            if isinstance(node, ast.FunctionDef) and node.name == "transcribe"
        )
        calls = [
            node
            for node in ast.walk(method)
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "_asr_pipe"
        ]
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertTrue(
                any(
                    kw.arg == "return_timestamps" and ast.literal_eval(kw.value)
                    for kw in call.keywords
                )
            )
        # Run the actual file-path branch without importing the heavyweight model.
        method.decorator_list = []
        method.returns = None
        for arg in method.args.args:
            arg.annotation = None
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "transcribe", "exec"), namespace)
        pipe = Mock(return_value={"text": " full transcript "})
        self.assertEqual(
            namespace["transcribe"](SimpleNamespace(_asr_pipe=pipe), "long.wav"), "full transcript"
        )
        pipe.assert_called_once_with("long.wav", return_timestamps=True)

    def test_config_migration_copies_profile_once_without_overwriting(self):
        (ROOT / "trash").mkdir(exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix="config-migration-", dir=ROOT / "trash"))
        program = scratch / "program"
        profile = scratch / "profile"
        profile.mkdir()
        old = profile / "settings.json"
        old.write_text(json.dumps({"language": "pl", "font_size": 14}), encoding="utf-8")
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
            patch.object(config, "_legacy_profile_dir", return_value=profile),
        ):
            config.migrate_legacy_user_data()
            self.assertTrue(old.is_file())
            self.assertEqual(config.load_config(config.CONFIG_FILE)["font_size"], 14)
            old.write_text('{"font_size": 20}', encoding="utf-8")
            config.migrate_legacy_user_data()
            self.assertEqual(config.load_config(config.CONFIG_FILE)["font_size"], 14)

    def test_corrupt_profile_can_use_old_portable_settings(self):
        (ROOT / "trash").mkdir(exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix="config-migration-", dir=ROOT / "trash"))
        profile = scratch / "profile"
        profile.mkdir()
        (profile / "settings.json").write_text("broken", encoding="utf-8")
        (scratch / "settings.json").write_text('{"language": "pl"}', encoding="utf-8")
        with (
            patch.multiple(
                config,
                PROGRAM_DIR=scratch,
                PROJECT_ROOT=scratch,
                APP_DATA_DIR=scratch / "config",
                CONFIG_FILE=scratch / "config/settings.json",
                TEMP_DIR=scratch / "config/temp",
                PRESETS_DIR=scratch / "presets",
            ),
            patch.object(config, "_legacy_profile_dir", return_value=profile),
        ):
            with self.assertLogs("omnisonic.config", "WARNING"):
                config.migrate_legacy_user_data()
            self.assertEqual(config.load_config(config.CONFIG_FILE)["language"], "pl")


if __name__ == "__main__":
    unittest.main()
