"""Normalization preflight, localization, and dispatch without a GPU runtime."""

import ast
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from omnisonic.i18n import load_locales, translate
from omnisonic.randomness import seeded_generation
from omnisonic.validation import operation_error_message

ROOT = Path(__file__).resolve().parents[1]
NORMALIZATION_ERROR_KEYS = (
    "normalization_missing_dependency",
    "normalization_unsupported_language",
    "normalization_failed",
)


class NormalizationError(ValueError):
    def __init__(self, key, language):
        super().__init__("Untranslated engine error")
        self.message_key = key
        self.language = language


class NormalizationUITests(unittest.TestCase):
    def setUp(self):
        self.locales = load_locales((ROOT / "langs",))
        self.wx = Mock(OK=1, ICON_ERROR=2, NOT_FOUND=-1)
        self.support = Mock(return_value="num2words")
        module = SimpleNamespace(
            TextNormalizationError=NormalizationError,
            check_normalization_support=self.support,
        )
        self.modules = patch.dict(sys.modules, {"omnivoice.utils.text": module})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.frame = Mock(cfg={"normalize_text": True})
        self.frame._.side_effect = lambda key: translate(self.locales, "pl", key)
        self.frame._CanUseModel.return_value = True
        self.frame.combo_presets.GetSelection.return_value = -1
        self.frame.audio_data = object()
        self.frame.batch_items = [SimpleNamespace(status="pending")]
        self.frame.batch_mode.GetSelection.return_value = 2
        for prefix in ("clone", "auto", "design"):
            getattr(self.frame, prefix + "_text").GetValue.return_value = "Mam 12 jabłek."
            getattr(self.frame, prefix + "_lang").GetValue.return_value = "Auto"
        self.frame._CheckTextNormalization = self.handler("_CheckTextNormalization").__get__(
            self.frame
        )

    def handler(self, name, **extra_namespace):
        filename = "batch_ui.py" if name in {"OnGenBatch", "_GenBatchWorker"} else "app.py"
        tree = ast.parse((ROOT / "omnisonic" / filename).read_text(encoding="utf-8"))
        node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        namespace = {
            "wx": self.wx,
            "operation_error_message": operation_error_message,
            "seeded_generation": seeded_generation,
        }
        namespace.update(extra_namespace)
        exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
        return namespace[name]

    def test_disabled_normalization_does_not_check_or_require_a_language(self):
        self.frame.cfg["normalize_text"] = False
        self.assertTrue(self.frame._CheckTextNormalization(None))
        self.assertTrue(self.frame._CheckTextNormalization("Japanese"))
        self.support.assert_not_called()
        self.wx.MessageBox.assert_not_called()

    def test_auto_rejected_in_every_mode_without_discarding_previous_audio(self):
        previous = self.frame.audio_data
        for method in ("OnGenClone", "OnGenDesign", "OnGenAuto", "OnGenBatch"):
            with self.subTest(method=method):
                self.wx.MessageBox.reset_mock()
                self.handler(method)(self.frame, None)
                self.wx.MessageBox.assert_called_once()
                self.assertIn("Wybierz język", self.wx.MessageBox.call_args.args[0])
                self.assertIs(self.frame.audio_data, previous)
                self.frame._prepare_generation.assert_not_called()
                self.frame.RunModelOperation.assert_not_called()
        self.support.assert_not_called()

    def test_explicit_language_accepted_and_forwarded_to_capability_check(self):
        for language in ("Polish", "English", "pl", "en"):
            with self.subTest(language=language):
                self.assertTrue(self.frame._CheckTextNormalization(language))
                self.support.assert_called_with(language)
        self.wx.MessageBox.assert_not_called()

    def test_support_errors_are_localized_with_language_and_reject_generation(self):
        for locale in ("pl", "en"):
            self.frame._.side_effect = lambda key, locale=locale: translate(
                self.locales, locale, key
            )
            for key in NORMALIZATION_ERROR_KEYS:
                with self.subTest(locale=locale, key=key):
                    error = NormalizationError(key, "ja")
                    self.support.side_effect = error
                    self.assertFalse(self.frame._CheckTextNormalization("Japanese"))
                    message = self.wx.MessageBox.call_args.args[0]
                    self.assertEqual(message, self.locales[locale][key].format(language="ja"))
                    self.assertNotIn("Untranslated", message)

    def test_late_operation_errors_are_localized_and_skip_success_callback(self):
        handler = self.handler("_complete_operation")
        self.frame._models.needs_collection = False
        for locale in ("pl", "en"):
            self.frame._.side_effect = lambda key, locale=locale: translate(
                self.locales, locale, key
            )
            for key in NORMALIZATION_ERROR_KEYS:
                with self.subTest(locale=locale, key=key):
                    self.wx.reset_mock()
                    self.frame.Log.reset_mock()
                    callback = Mock()
                    state = SimpleNamespace(
                        error=NormalizationError(key, "bo"), cancel_flag=False, result=None
                    )
                    handler(self.frame, state, callback)
                    message = self.locales[locale]["msg_error"] + self.locales[locale][key].format(
                        language="bo"
                    )
                    self.frame.Log.assert_called_once_with(message)
                    self.wx.MessageBox.assert_called_once_with(
                        message,
                        self.locales[locale]["error_title"],
                        self.wx.OK | self.wx.ICON_ERROR,
                    )
                    callback.assert_not_called()

    def test_late_batch_errors_are_localized_without_writing_audio_or_opening_dialogs(self):
        array_module = SimpleNamespace(asarray=Mock())
        audio_module = SimpleNamespace(write=Mock())
        prompt_type = Mock()
        modules = {
            "numpy": array_module,
            "soundfile": audio_module,
            "omnivoice": SimpleNamespace(VoiceClonePrompt=prompt_type),
            "torch": None,
        }
        for locale in ("pl", "en"):
            self.frame._.side_effect = lambda key, locale=locale: translate(
                self.locales, locale, key
            )
            for key in NORMALIZATION_ERROR_KEYS:
                with self.subTest(locale=locale, key=key), patch.dict(sys.modules, modules):
                    error = NormalizationError(key, "bo")
                    model = Mock()
                    model.generate.side_effect = error
                    self.wx.reset_mock()

                    def process(inputs, output, state, synthesize, save, progress, **kwargs):
                        return synthesize("12")

                    process_batch = Mock(side_effect=process)
                    handler = self.handler("_GenBatchWorker", process_text_batch=process_batch)
                    with self.assertRaises(ValueError) as caught:
                        handler(
                            self.frame,
                            Mock(),
                            model,
                            (),
                            None,
                            {"normalize_text": True, "language": "bo"},
                            None,
                            (),
                            False,
                        )
                    self.assertEqual(
                        str(caught.exception), self.locales[locale][key].format(language="bo")
                    )
                    self.assertIs(caught.exception.__cause__, error)
                    process_batch.assert_called_once()
                    model.generate.assert_called_once_with(
                        text="12", normalize_text=True, language="bo"
                    )
                    array_module.asarray.assert_not_called()
                    audio_module.write.assert_not_called()
                    prompt_type.load.assert_not_called()
                    self.wx.MessageBox.assert_not_called()

    def test_unrelated_errors_keep_their_details(self):
        for error in (ValueError("Original details"), NormalizationError("unknown", "en")):
            self.assertEqual(operation_error_message(error, self.frame._), str(error))


if __name__ == "__main__":
    unittest.main()
