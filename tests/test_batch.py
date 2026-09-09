from __future__ import annotations

import ast
import codecs
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from omnisonic.batch import (
    BatchInput,
    BatchInputError,
    discover_text_files,
    plan_batch_outputs,
    process_text_batch,
    read_text_input,
)
from omnisonic.i18n import load_locales
from omnisonic.operations import OperationCancelled, OperationState


ROOT = Path(__file__).resolve().parents[1]


class BatchSettingsTests(unittest.TestCase):
    def test_settings_update_batch_folder_only_after_saving_a_changed_directory(self):
        # Exercise the actual settings handler without importing wx or a model in CI.
        tree = ast.parse((ROOT / "omnisonic/app.py").read_text(encoding="utf-8"))
        frame_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "OmniVoiceFrame"
        )
        handler = next(
            node
            for node in frame_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "OnOpenSettings"
        )
        code = compile(ast.Module(body=[handler], type_ignores=[]), "settings-handler", "exec")
        for changed, accepted, save_error in (
            (True, True, None),
            (False, True, None),
            (True, False, None),
            (True, True, OSError("Cannot save settings")),
        ):
            with self.subTest(changed=changed, accepted=accepted, save_error=save_error):
                original = {"language": "en", "generated_audio_directory": "old"}
                updated = dict(original, generated_audio_directory="new" if changed else "old")
                frame = Mock(cfg=original, model=None)
                dialog = Mock(cfg=updated)
                dialog.ShowModal.return_value = 1 if accepted else 0
                save = Mock(side_effect=save_error)
                namespace = {
                    "SettingsDialog": Mock(return_value=dialog),
                    "SaveBasicConfig": save,
                    "wx": SimpleNamespace(ID_OK=1, OK=2, ICON_ERROR=4, MessageBox=Mock()),
                }
                exec(code, namespace)
                namespace["OnOpenSettings"](frame, None)
                if accepted and save_error is None:
                    self.assertIs(frame.cfg, updated)
                    save.assert_called_once_with(updated)
                    if changed:
                        frame.batch_output.SetValue.assert_called_once_with("new")
                    else:
                        # Unrelated settings must not reset a manually chosen batch folder.
                        frame.batch_output.SetValue.assert_not_called()
                else:
                    self.assertIs(frame.cfg, original)
                    frame.batch_output.SetValue.assert_not_called()
                dialog.Destroy.assert_called_once()


class BatchTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "trash").mkdir(exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix="batch-unit-", dir=ROOT / "trash"))

    def text_file(self, name, text="Example text"):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    @staticmethod
    def save_audio(path, audio):
        path.write_text(audio, encoding="utf-8")

    def test_multiple_files_folders_and_overlaps_are_deduplicated(self):
        a = self.text_file("first/a.txt")
        b = self.text_file("first/nested/b.md")
        c = self.text_file("second/c.TXT")
        self.text_file("second/ignored.json")
        found, errors = discover_text_files([a, a.parent, self.directory / "second", b.parent])
        self.assertEqual([item.path for item in found], [a, b, c])
        self.assertEqual([item.root for item in found], [None, a.parent, c.parent])
        self.assertEqual(errors, [])
        self.assertEqual(discover_text_files([a.parent], existing=[a, b])[0], [])

    def test_recursion_can_be_disabled(self):
        a = self.text_file("a.txt")
        self.text_file("nested/b.txt")
        found, _ = discover_text_files([self.directory], recursive=False)
        self.assertEqual(found, [BatchInput(a, self.directory)])

    def test_missing_unsupported_and_link_inputs_are_reported(self):
        unsupported = self.text_file("unsupported.pdf")
        found, errors = discover_text_files([unsupported, self.directory / "missing.txt"])
        self.assertEqual(found, [])
        self.assertEqual(len(errors), 2)
        with patch("omnisonic.batch._is_link", return_value=True):
            self.assertEqual(discover_text_files([unsupported])[1][0][1], "batch_link_skipped")

    def test_queue_limit_counts_each_file_once(self):
        paths = [self.text_file(f"{index}.txt") for index in range(3)]
        with patch("omnisonic.batch.MAX_BATCH_FILES", 2):
            self.assertEqual(len(discover_text_files(paths[:2])[0]), 2)
            with self.assertRaisesRegex(BatchInputError, "batch_limit"):
                discover_text_files(paths)

    def test_unicode_and_bom_encodings(self):
        text = "Zażółć gęślą jaźń. 日本語"
        for encoding in ("utf-8", "utf-8-sig", "utf-16"):
            path = self.directory / f"{encoding}.txt"
            path.write_bytes(text.encode(encoding))
            self.assertEqual(read_text_input(path), text)
        path.write_bytes(codecs.BOM_UTF16_BE + text.encode("utf-16-be"))
        self.assertEqual(read_text_input(path), text)

    def test_invalid_empty_and_oversized_text_is_rejected(self):
        path = self.text_file("empty.txt", " \n ")
        with self.assertRaisesRegex(BatchInputError, "batch_empty_file"):
            read_text_input(path)
        path.write_bytes(b"\xff\x00")
        with self.assertRaisesRegex(BatchInputError, "batch_encoding_error"):
            read_text_input(path)
        path.write_bytes(b"a" * 9)
        with patch("omnisonic.batch.MAX_TEXT_BYTES", 8):
            with self.assertRaisesRegex(BatchInputError, "batch_too_large"):
                read_text_input(path)

    def test_same_names_get_separate_outputs_and_report(self):
        a, b = self.text_file("one/a.txt", "First"), self.text_file("two/a.txt", "Second")
        output = self.directory / "output"
        results = process_text_batch(
            [BatchInput(a), BatchInput(b)], output, OperationState(), str.upper, self.save_audio
        )
        self.assertEqual([item.status for item in results], ["done", "done"])
        self.assertNotEqual(results[0].output, results[1].output)
        self.assertEqual(Path(results[1].output).read_text(), "SECOND")
        report = json.loads((output / "batch_report.json").read_text(encoding="utf-8"))
        self.assertFalse(report["cancelled"])
        with self.assertRaises(FileExistsError):
            process_text_batch([BatchInput(a)], output, OperationState(), str, self.save_audio)

    def test_bad_file_does_not_stop_remaining_files(self):
        paths = [BatchInput(self.text_file("a.txt", "")), BatchInput(self.text_file("b.txt"))]
        result = process_text_batch(
            paths, self.directory / "out", OperationState(), str, self.save_audio
        )
        self.assertEqual([item.status for item in result], ["failed", "done"])

    def test_failed_save_removes_partial_file_and_continues(self):
        paths = [BatchInput(self.text_file("a.txt", "First")), BatchInput(self.text_file("b.txt"))]

        def save(path, audio):
            path.write_text(audio)
            if audio == "First":
                raise OSError("Simulated disk error")

        output = self.directory / "out"
        result = process_text_batch(paths, output, OperationState(), str, save)
        self.assertEqual([item.status for item in result], ["failed", "done"])
        self.assertEqual(list(output.glob("*.part.wav")), [])

    def test_cancellation_keeps_completed_files_and_records_report(self):
        paths = [BatchInput(self.text_file("a.txt")), BatchInput(self.text_file("b.txt"))]
        state = OperationState()

        def progress(_index, result):
            if result.status == "done":
                state.request_cancel()

        output = self.directory / "out"
        with self.assertRaises(OperationCancelled):
            process_text_batch(paths, output, state, str, self.save_audio, progress)
        self.assertEqual(len(list(output.glob("*.wav"))), 1)
        report = json.loads((output / "batch_report.json").read_text())
        self.assertTrue(report["cancelled"])
        self.assertEqual(report["files"][1]["status"], "queued")

    def test_mid_generation_cancellation_does_not_publish_partial_output(self):
        path = self.text_file("a.txt")
        state = OperationState()

        def synthesize(text):
            state.request_cancel()
            return text

        output = self.directory / "out"
        with self.assertRaises(OperationCancelled):
            process_text_batch([BatchInput(path)], output, state, synthesize, self.save_audio)
        self.assertEqual(list(output.glob("*.wav")), [])
        report = json.loads((output / "batch_report.json").read_text())
        self.assertEqual(report["files"][0]["status"], "cancelled")

    def test_progress_state_is_bounded(self):
        state = OperationState()
        state.set_progress(9, 3, "Current file")
        self.assertEqual(state.get_progress(), (3, 3, "Current file"))

    def test_preserves_multiple_selected_folders_and_nested_paths(self):
        a = self.text_file("Book/Chapter 1/part.txt", "First")
        b = self.text_file("Book/intro.md", "Second")
        c = self.text_file("Notes/note.txt", "Third")
        standalone = self.text_file("separate.txt", "Fourth")
        inputs, errors = discover_text_files(
            [self.directory / "Book", self.directory / "Notes", standalone]
        )
        self.assertEqual(errors, [])
        planned = plan_batch_outputs(inputs, True)
        self.assertEqual(
            planned,
            [
                Path("Book/Chapter 1/part.wav"),
                Path("Book/intro.wav"),
                Path("Notes/note.wav"),
                Path("separate.wav"),
            ],
        )
        output = self.directory / "out"
        results = process_text_batch(
            inputs, output, OperationState(), str, self.save_audio, preserve_structure=True
        )
        self.assertTrue(all(item.status == "done" for item in results))
        self.assertEqual([Path(item.output).relative_to(output) for item in results], planned)
        self.assertEqual(
            [Path(item.output).read_text() for item in results],
            [a.read_text(), b.read_text(), c.read_text(), standalone.read_text()],
        )
        self.assertEqual(results[0].source_root, str(self.directory / "Book"))
        report = json.loads((output / "batch_report.json").read_text())
        self.assertTrue(report["preserve_structure"])
        # Toggling after scanning does not lose the original folder metadata.
        self.assertTrue(all(len(path.parts) == 1 for path in plan_batch_outputs(inputs, False)))

    def test_same_folder_names_stay_separate_and_same_stems_do_not_overwrite(self):
        a = self.text_file("first/Voices/sample.txt")
        b = self.text_file("first/Voices/sample.md")
        c = self.text_file("second/Voices/deep/sample.txt")
        inputs, _ = discover_text_files([a.parent, c.parent.parent])
        self.assertEqual(
            plan_batch_outputs(inputs, True),
            [
                Path("Voices/sample.wav"),
                Path("Voices/sample (2).wav"),
                Path("Voices (2)/deep/sample.wav"),
            ],
        )
        self.assertEqual({item.path for item in inputs}, {a, b, c})

    def test_overlapping_folder_selections_keep_first_origin_without_duplicates(self):
        path = self.text_file("Book/nested/part.txt")
        inputs, _ = discover_text_files([path.parent, path.parent.parent])
        self.assertEqual(inputs, [BatchInput(path, path.parent)])
        inputs, _ = discover_text_files([path.parent.parent, path.parent])
        self.assertEqual(inputs, [BatchInput(path, path.parent.parent)])
        self.assertEqual(discover_text_files([path.parent], existing=[path])[0], [])

    def test_folder_file_and_report_names_cannot_collide(self):
        a = self.text_file("voice.wav/a.txt")
        b = self.text_file("voice.txt")
        c = self.text_file("batch_report.json/a.txt")
        inputs, _ = discover_text_files([b, a.parent, c.parent])
        output = self.directory / "out"
        results = process_text_batch(
            inputs, output, OperationState(), str, self.save_audio, preserve_structure=True
        )
        self.assertEqual(
            [Path(item.output).relative_to(output) for item in results],
            [Path("voice (2).wav"), Path("voice.wav/a.wav"), Path("batch_report.json (2)/a.wav")],
        )
        self.assertTrue((output / "batch_report.json").is_file())

    def test_temporary_audio_cannot_overwrite_a_completed_part_named_source(self):
        inputs = [
            BatchInput(self.text_file("voice.part.txt", "First")),
            BatchInput(self.text_file("voice.txt", "Second")),
        ]
        results = process_text_batch(
            inputs,
            self.directory / "out",
            OperationState(),
            str,
            self.save_audio,
            preserve_structure=True,
        )
        self.assertEqual([Path(item.output).read_text() for item in results], ["First", "Second"])
        self.assertEqual(
            [Path(item.output).name for item in results], ["voice.part.wav", "voice.wav"]
        )

    def test_output_paths_are_relative_safe_and_case_insensitively_unique(self):
        inputs = [
            BatchInput(Path(name)) for name in ("CON.txt", "NUL.md", "a.txt", "A.md", "..txt")
        ]
        outputs = plan_batch_outputs(inputs, True)
        self.assertEqual(outputs[:2], [Path("_CON.wav"), Path("_NUL.wav")])
        self.assertEqual(len({str(path).casefold() for path in outputs}), len(outputs))
        self.assertTrue(all(not path.is_absolute() and ".." not in path.parts for path in outputs))
        with self.assertRaises(ValueError):
            process_text_batch(
                [BatchInput(self.directory / "outside.txt", self.directory / "selected")],
                self.directory / "invalid-out",
                OperationState(),
                str,
                self.save_audio,
                preserve_structure=True,
            )
        self.assertFalse((self.directory / "invalid-out").exists())

    def test_structured_cancellation_preserves_completed_output_and_origin(self):
        a = self.text_file("Book/a/part.txt")
        self.text_file("Book/b/part.txt")
        inputs, _ = discover_text_files([self.directory / "Book"])
        state = OperationState()

        def progress(_index, result):
            if result.status == "done":
                state.request_cancel()

        output = self.directory / "out"
        with self.assertRaises(OperationCancelled):
            process_text_batch(
                inputs, output, state, str, self.save_audio, progress, preserve_structure=True
            )
        self.assertTrue((output / "Book/a/part.wav").is_file())
        report = json.loads((output / "batch_report.json").read_text())
        self.assertEqual(report["files"][0]["source_root"], str(a.parent.parent))
        self.assertEqual(report["files"][1]["status"], "queued")

    def test_batch_ui_translations_exist_in_both_languages(self):
        locales = load_locales((ROOT / "langs",))
        tree = ast.parse((ROOT / "omnisonic/batch_ui.py").read_text(encoding="utf-8"))
        keys = {
            "batch_" + status for status in ("queued", "running", "done", "failed", "cancelled")
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith("batch_") and node.value in locales["en"]:
                    keys.add(node.value)
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "_":
                if node.args and isinstance(node.args[0], ast.Constant):
                    keys.add(node.args[0].value)
        for language in ("en", "pl"):
            self.assertFalse(keys - locales[language].keys())


if __name__ == "__main__":
    unittest.main()
