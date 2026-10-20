"""Exercise actual batch workers and WAV timelines without neural models or wx."""

import ast
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from omnisonic.batch import BatchInput, discover_text_files, process_text_batch
from omnisonic.files import atomic_write, write_numbered_audio
from omnisonic.i18n import load_locales, translate
from omnisonic.operations import OperationCancelled, OperationState
from omnisonic.randomness import seeded_generation
from omnisonic.validation import operation_error_message, safe_child_path
from tests.materials import scratch_directory

ROOT = Path(__file__).resolve().parents[1]


def batch_worker(**namespace):
    source = ROOT / "omnisonic/batch_ui.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_GenBatchWorker"
    )
    values = dict(
        Path=Path,
        process_text_batch=process_text_batch,
        seeded_generation=seeded_generation,
        operation_error_message=operation_error_message,
        safe_child_path=safe_child_path,
        PRESETS_DIR=ROOT / "presets",
        wx=SimpleNamespace(CallAfter=lambda callback, *args: callback(*args)),
    )
    values.update(namespace)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), values)
    return values[node.name]


class SubtitleBatchTests(unittest.TestCase):
    def setUp(self):
        self.scratch = scratch_directory("subtitle-batch-")
        self.locales = load_locales((ROOT / "langs",))
        self.frame = Mock()
        self.frame._.side_effect = lambda key: translate(self.locales, "en", key)
        self.model = SimpleNamespace(device="cpu", sampling_rate=24000, generate=Mock())
        self.config = SimpleNamespace(
            preprocess_prompt=True,
            postprocess_output=True,
            pad_duration=0.1,
            fade_duration=0.2,
            audio_chunk_threshold=30.0,
        )
        self.kwargs = {"generation_config": self.config, "speed": 1.8, "language": "en"}
        self.state = OperationState()
        self.prompt_type = SimpleNamespace(load=Mock(return_value=object()))
        self.modules = patch.dict(
            sys.modules, {"omnivoice": SimpleNamespace(VoiceClonePrompt=self.prompt_type)}
        )
        self.modules.start()
        self.addCleanup(self.modules.stop)

        def generate(**kwargs):
            frames = round(kwargs.get("duration", 0.25) * 24000) - 240
            return [np.full(frames, 0.2, dtype=np.float32)]

        self.model.generate.side_effect = generate

    def subtitle(self, name="movie.srt", text=None):
        path = self.scratch / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            text = (
                "1\n00:00:01,000 --> 00:00:01,500\n<i>First sentence.</i>\n\n"
                "2\n00:00:02,000 --> 00:00:03,000\nSecond sentence.\n"
            )
        path.write_text(text, encoding="utf-8")
        return path

    def run_batch(self, paths, *, state=None, prompt=None, namespace=None, seed=None):
        output = self.scratch / ("output-" + str(len(list(self.scratch.glob("output-*")))))
        results = batch_worker(**(namespace or {}))(
            self.frame,
            state or self.state,
            self.model,
            tuple(range(len(paths))),
            output,
            self.kwargs,
            prompt,
            tuple(BatchInput(path) for path in paths),
            False,
            seed,
        )
        return results, output

    def test_actual_wav_has_exact_cue_positions_silence_and_source_name(self):
        source = self.subtitle()
        results, output = self.run_batch([source])
        self.assertEqual(results[0].status, "done", results[0].error)
        destination = Path(results[0].output)
        self.assertEqual(destination.name, "movie.wav")
        audio, sample_rate = sf.read(destination, dtype="float32")
        self.assertEqual((sample_rate, len(audio)), (24000, 72000))
        for start, end in ((0, 24000), (35760, 48000), (71760, 72000)):
            self.assertTrue(np.all(audio[start:end] == 0))
        for start, end in ((24000, 35760), (48000, 71760)):
            np.testing.assert_allclose(audio[start:end], 0.2, atol=1 / 32768)
        self.assertEqual(
            [call.kwargs["text"] for call in self.model.generate.call_args_list],
            ["First sentence.", "Second sentence."],
        )
        self.assertTrue((output / "batch_report.json").is_file())
        self.assertEqual(
            [call.args[0] for call in self.frame.Log.call_args_list],
            ["movie.srt: subtitle 1/2", "movie.srt: subtitle 2/2"],
        )
        self.assertEqual(source.read_text(encoding="utf-8").splitlines()[0], "1")

    def test_timed_config_is_independent_and_subtitle_duration_overrides_ui(self):
        self.kwargs["duration"] = 99
        self.run_batch([self.subtitle()])
        calls = self.model.generate.call_args_list
        self.assertEqual([call.kwargs["duration"] for call in calls], [0.5, 1.0])
        for call in calls:
            self.assertNotIn("speed", call.kwargs)
            timed = call.kwargs["generation_config"]
            self.assertIsNot(timed, self.config)
            self.assertEqual(timed.pad_duration, 0)
            self.assertFalse(timed.postprocess_output)
            self.assertGreater(timed.audio_chunk_threshold, 120)
            self.assertEqual(call.kwargs["language"], "en")
        self.assertEqual(self.config.pad_duration, 0.1)
        self.assertTrue(self.config.postprocess_output)
        self.assertEqual(self.config.audio_chunk_threshold, 30)
        self.assertEqual(self.kwargs["duration"], 99)

    def test_vtt_metadata_is_not_spoken_and_reference_seed_reused_per_cue(self):
        source = self.subtitle(
            "movie.vtt",
            "WEBVTT\n\nintro\n00:01.000 --> 00:01.500 align:start\n"
            "<v Narrator>First sentence.</v>\n\n00:02.000 --> 00:03.000\nSecond sentence.\n",
        )
        entries = []

        @contextmanager
        def scope(seed, device):
            entries.append((seed, device))
            yield

        reference = object()
        self.frame._models.reference_prompt.return_value = reference
        results, _ = self.run_batch(
            [source],
            prompt=(None, "synthetic-reference.wav", "Reference."),
            namespace={"seeded_generation": scope},
            seed=42,
        )
        self.assertEqual(results[0].status, "done", results[0].error)
        self.assertEqual(entries, [(42, "cpu"), (42, "cpu")])
        self.frame._models.reference_prompt.assert_called_once()
        self.assertTrue(
            all(
                call.kwargs["voice_clone_prompt"] is reference
                for call in self.model.generate.call_args_list
            )
        )

    def test_invalid_subtitles_are_localized_and_other_files_continue(self):
        bad = self.subtitle(
            text=(
                "1\n00:00:01,000 --> 00:00:02,000\nFirst.\n\n"
                "2\n00:00:01,500 --> 00:00:03,000\nSecond.\n"
            )
        )
        text_file = self.scratch / "plain.txt"
        text_file.write_text("Regular input.", encoding="utf-8")
        for language in ("pl", "en"):
            self.frame._.side_effect = lambda key, lang=language: translate(self.locales, lang, key)
            self.model.generate.reset_mock()
            results, output = self.run_batch([bad, text_file])
            self.assertEqual([item.status for item in results], ["failed", "done"])
            self.assertEqual(
                results[0].error,
                self.locales[language]["subtitle_overlap"].format(index=2, previous=1),
            )
            self.model.generate.assert_called_once()
            self.assertFalse((output / "movie.wav").exists())
            self.assertTrue((output / "plain.wav").is_file())
        self.assertEqual(self.frame._models.clear_reference_prompt_cache.call_count, 2)

    def test_overflow_or_mid_cue_cancellation_never_publish_partial_track(self):
        source = self.subtitle()
        self.model.generate.return_value = [np.ones(24000, dtype=np.float32)]
        self.model.generate.side_effect = None
        results, output = self.run_batch([source])
        self.assertEqual(results[0].status, "failed")
        self.assertIn("0.500", results[0].error)
        self.assertEqual(list(output.glob("*.wav")), [])
        self.assertEqual(list(output.glob(".omnisonic-*")), [])

        def cancel(**kwargs):
            self.state.request_cancel()
            return [np.zeros(12000, dtype=np.float32)]

        self.model.generate.side_effect = cancel
        with self.assertRaises(OperationCancelled):
            self.run_batch([source])
        cancelled_output = self.scratch / "output-1"
        self.assertEqual(list(cancelled_output.glob("*.wav")), [])
        report = json.loads((cancelled_output / "batch_report.json").read_text(encoding="utf-8"))
        self.assertTrue(report["cancelled"])
        self.assertEqual(report["files"][0]["status"], "cancelled")

    def test_model_failure_identifies_the_affected_subtitle_in_both_locales(self):
        source = self.subtitle()
        for language in ("pl", "en"):
            self.frame._.side_effect = lambda key, lang=language: translate(self.locales, lang, key)
            self.model.generate.side_effect = [
                [np.zeros(12000, dtype=np.float32)],
                RuntimeError("Synthetic inference failure"),
            ]
            results, output = self.run_batch([source])
            self.assertEqual(results[0].status, "failed")
            self.assertEqual(
                results[0].error,
                self.locales[language]["subtitle_generation_failed"].format(
                    index=2, error="Synthetic inference failure"
                ),
            )
            self.assertEqual(list(output.glob("*.wav")), [])

    def test_discovery_and_mixed_text_subtitle_output_preserve_folder_origins(self):
        source = self.subtitle("Book/Nested/movie.srt")
        vtt = self.subtitle("Book/other.VTT", "WEBVTT\n\n00:00.000 --> 00:01.000\nHello.\n")
        text_file = self.scratch / "Book/plain.txt"
        text_file.write_text("Plain text.", encoding="utf-8")
        found, errors = discover_text_files([self.scratch / "Book"])
        self.assertEqual(errors, [])
        self.assertEqual({item.path for item in found}, {source, vtt, text_file})
        output = self.scratch / "structured"
        results = batch_worker()(
            self.frame,
            self.state,
            self.model,
            (0, 1, 2),
            output,
            self.kwargs,
            None,
            tuple(found),
            True,
        )
        self.assertTrue(all(item.status == "done" for item in results), results)
        self.assertTrue((output / "Book/Nested/movie.wav").is_file())
        self.assertTrue((output / "Book/other.wav").is_file())
        self.assertTrue((output / "Book/plain.wav").is_file())


class OutputFailureTests(unittest.TestCase):
    def setUp(self):
        self.scratch = scratch_directory("subtitle-save-failure-")

    def test_report_failure_does_not_hide_a_cancelled_generation(self):
        source = self.scratch / "input.txt"
        source.write_text("Synthetic input.", encoding="utf-8")
        state = OperationState()

        def cancel(text):
            state.request_cancel()
            return text

        with patch("omnisonic.batch.atomic_write", side_effect=PermissionError("Report lock")):
            with (
                self.assertLogs("omnisonic.batch", "WARNING"),
                self.assertRaises(OperationCancelled),
            ):
                process_text_batch(
                    [BatchInput(source)], self.scratch / "out", state, cancel, Mock()
                )

    def test_report_failure_after_success_is_visible_and_keeps_finished_audio(self):
        source = self.scratch / "input.txt"
        source.write_text("Synthetic input.", encoding="utf-8")
        output = self.scratch / "out"
        with patch("omnisonic.batch.atomic_write", side_effect=PermissionError("Report lock")):
            with self.assertRaisesRegex(PermissionError, "Report lock"):
                process_text_batch(
                    [BatchInput(source)],
                    output,
                    OperationState(),
                    str,
                    lambda path, audio: path.write_text(audio, encoding="utf-8"),
                )
        self.assertEqual((output / "input.wav").read_text(), "Synthetic input.")

    def test_locked_partial_cleanup_preserves_primary_write_error_and_existing_file(self):
        destination = self.scratch / "existing.wav"
        destination.write_bytes(b"existing audio")

        def fail(path):
            Path(path).write_bytes(b"partial audio")
            raise OSError("Primary write failure")

        with patch.object(Path, "unlink", side_effect=PermissionError("Cleanup lock")):
            with self.assertLogs("omnisonic.files", "WARNING"):
                with self.assertRaisesRegex(OSError, "Primary write failure"):
                    atomic_write(destination, fail)
                with self.assertRaisesRegex(OSError, "Primary write failure"):
                    write_numbered_audio(self.scratch, "generated", fail)
        self.assertEqual(destination.read_bytes(), b"existing audio")

    def test_unrelated_caller_exception_does_not_hide_a_report_failure(self):
        source = self.scratch / "input.txt"
        source.write_text("Synthetic input.", encoding="utf-8")
        with patch("omnisonic.batch.atomic_write", side_effect=PermissionError("Report lock")):
            with self.assertRaisesRegex(PermissionError, "Report lock"):
                try:
                    raise RuntimeError("Unrelated caller context")
                except RuntimeError:
                    process_text_batch(
                        [BatchInput(source)],
                        self.scratch / "out",
                        OperationState(),
                        str,
                        lambda path, audio: path.write_text(audio, encoding="utf-8"),
                    )


if __name__ == "__main__":
    unittest.main()
