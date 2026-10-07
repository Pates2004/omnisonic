"""Quoted Windows output paths through real handlers, with only synthetic data."""

import ast
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from omnisonic.batch import BatchInput, BatchResult, process_text_batch
from omnisonic.config import DEFAULT_CONFIG, normalize_config
from omnisonic.i18n import load_locales, translate
from omnisonic.operations import OperationState
from omnisonic.validation import (
    FilenameValidationError,
    normalize_pasted_path,
    output_directory_path,
    validation_error_message,
)

ROOT = Path(__file__).resolve().parents[1]


def handler(filename, name, **namespace):
    tree = ast.parse((ROOT / "omnisonic" / filename).read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace.update(
        Path=Path,
        normalize_pasted_path=normalize_pasted_path,
        output_directory_path=output_directory_path,
        validation_error_message=validation_error_message,
    )
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


class OutputPathTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "trash").mkdir(exist_ok=True)
        self.scratch = Path(tempfile.mkdtemp(prefix="output-paths-", dir=ROOT / "trash"))
        self.locales = load_locales((ROOT / "langs",))

    def test_copy_as_path_only_removes_one_complete_double_quote_wrapper(self):
        for original, expected in (
            ('  "D:\\studio\\book\\output"  ', r"D:\studio\book\output"),
            ('""', ""),
            ("  plain path  ", "plain path"),
            ('" inner space "', " inner space "),
            ("O'Brien's recordings", "O'Brien's recordings"),
            ("'literal folder'", "'literal folder'"),
            ('"unfinished', '"unfinished'),
            ('""nested""', '""nested""'),
            ('"directory"/child', '"directory"/child'),
        ):
            with self.subTest(original=original):
                self.assertEqual(normalize_pasted_path(original), expected)

    @unittest.skipUnless(os.name == "nt", "Exact Windows path semantics")
    def test_reported_path_is_not_made_relative_by_literal_quotes(self):
        self.assertEqual(
            output_directory_path('"D:\\studio\\book\\output"'),
            Path(r"D:\studio\book\output"),
        )

    def test_quoted_environment_variable_is_expanded_without_shell_execution(self):
        directory = self.scratch / "space & apostrophe's"
        with patch.dict(os.environ, {"OMNISONIC_PATH_TEST": str(directory)}):
            self.assertEqual(output_directory_path('"$OMNISONIC_PATH_TEST"'), directory)
        self.assertFalse(directory.exists())

    def test_loaded_settings_preserve_path_meaning_across_repeated_normalization(self):
        for key in ("generated_audio_directory", "recorded_audio_directory"):
            with self.subTest(key=key):
                path = str(self.scratch / "output")
                for value in (f'"{path}"', '" leading-folder"', '"trailing-folder "'):
                    once = normalize_config({key: value})
                    twice = normalize_config(once)
                    self.assertEqual(once, twice)
                    self.assertEqual(output_directory_path(once[key]), output_directory_path(value))
                self.assertEqual(normalize_config({key: ""})[key], DEFAULT_CONFIG[key])
                self.assertEqual(normalize_config({key: "'literal'"})[key], "'literal'")

    def test_settings_validate_a_quoted_directory_without_creating_it(self):
        validate = handler("app.py", "_validated_audio_directory")
        directory = self.scratch / "chosen output"
        frame = Mock()
        frame._.side_effect = lambda key: translate(self.locales, "pl", key)
        for label in ("generated_folder_lbl", "recorded_folder_lbl"):
            control = Mock()
            control.GetValue.return_value = f'"{directory}"'
            self.assertEqual(validate(frame, control, label), str(directory))
            control.GetValue.return_value = '""'
            with self.assertRaises(ValueError):
                validate(frame, control, label)
        self.assertFalse(directory.exists())

    def test_relative_quoted_name_preserves_significant_leading_space_in_handlers(self):
        raw = '" leading-folder"'
        expected = output_directory_path(raw)
        control = Mock()
        control.GetValue.return_value = raw
        self.assertEqual(
            handler("app.py", "_validated_audio_directory")(Mock(), control, "folder"),
            str(expected),
        )
        frame, _ = self.batch_handler(raw)
        self.assertEqual(frame.RunModelOperation.call_args.args[4].parent, expected)

    def test_apostrophes_do_not_disable_later_environment_variable_expansion(self):
        base = self.scratch / "O'Brien"
        with patch.dict(os.environ, {"OMNISONIC_PATH_COMPONENT": "expanded"}):
            forms = ["$OMNISONIC_PATH_COMPONENT", "${OMNISONIC_PATH_COMPONENT}"]
            if os.name == "nt":
                forms.append("%OMNISONIC_PATH_COMPONENT%")
            for variable in forms:
                raw = f'"{base / variable}"'
                self.assertEqual(output_directory_path(raw), base / "expanded")

    def batch_handler(self, raw_path, locale="pl"):
        frame = Mock(cfg={})
        frame._.side_effect = lambda key: translate(self.locales, locale, key)
        source = self.scratch / "sentence.txt"
        source.write_text("Synthetic sentence.", encoding="utf-8")
        frame.batch_items = [BatchResult(str(source))]
        frame.batch_mode.GetSelection.return_value = 2
        frame.auto_lang.GetValue.return_value = "Auto"
        frame.batch_output.GetValue.return_value = raw_path
        frame.batch_preserve_structure.GetValue.return_value = False
        frame._GetGenerationSeed.return_value = None
        wx = Mock(OK=1, ICON_ERROR=2)
        handler(
            "batch_ui.py",
            "OnGenBatch",
            wx=wx,
            datetime=datetime,
            uuid4=uuid4,
            BatchInput=BatchInput,
            default_audio_directory=lambda kind: self.scratch / kind,
        )(frame, None)
        return frame, wx

    def test_real_batch_dispatch_and_save_accept_copy_as_path(self):
        directory = self.scratch / "chosen output & more"
        frame, wx = self.batch_handler(f'  "{directory}"  ')
        wx.MessageBox.assert_not_called()
        frame.RunModelOperation.assert_called_once()
        args = frame.RunModelOperation.call_args.args
        output = args[4]
        self.assertEqual(output.parent, directory)
        self.assertFalse(output.exists(), "UI dispatch must not create output directories")
        results = process_text_batch(
            list(args[7]),
            output,
            OperationState(),
            lambda text: text,
            lambda path, audio: path.write_text(audio, encoding="utf-8"),
        )
        self.assertEqual([item.status for item in results], ["done"])
        self.assertEqual(Path(results[0].output).read_text(encoding="utf-8"), "Synthetic sentence.")
        self.assertTrue((output / "batch_report.json").is_file())

    @unittest.skipUnless(os.name == "nt", "Quotes inside names are invalid on Windows")
    def test_misplaced_quotes_are_localized_before_loading_model_or_stopping_playback(self):
        for locale in ("pl", "en"):
            for value in ('"unfinished', '"directory"/child', '""nested""'):
                with self.subTest(locale=locale, value=value):
                    frame, wx = self.batch_handler(value, locale)
                    frame.RunModelOperation.assert_not_called()
                    frame.OnStopAudio.assert_not_called()
                    self.assertEqual(
                        wx.MessageBox.call_args.args[0], self.locales[locale]["folder_path_invalid"]
                    )

    def test_empty_and_nul_paths_fail_without_filesystem_mutation(self):
        for value in ("", '""', "\0"):
            with self.subTest(value=value), self.assertRaises(FilenameValidationError):
                output_directory_path(value)


if __name__ == "__main__":
    unittest.main()
