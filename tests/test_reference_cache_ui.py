"""Real clone/batch worker integration with lightweight synthetic conditioning."""

import ast
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from omnisonic.batch import BatchInput, process_text_batch
from omnisonic.model_lifecycle import ModelLifecycle
from omnisonic.operations import OperationCancelled, OperationState
from omnisonic.validation import safe_child_path
from tests.test_prompt_cache import Model, Prompt, Tokens


ROOT = Path(__file__).resolve().parents[1]


def load_worker(relative, name, namespace):
    source = ROOT / relative
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[name]


class ReferenceCacheWorkerTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "trash").mkdir(exist_ok=True)
        self.scratch = Path(tempfile.mkdtemp(prefix="reference-cache-ui-", dir=ROOT / "trash"))
        self.source = self.scratch / "synthetic-reference.bin"
        self.source.write_bytes(b"only a mocked audio decoder reads this")
        self.presets = self.scratch / "presets"
        self.presets.mkdir()
        (self.presets / "saved.pt").write_bytes(b"mocked preset loader")
        self.inputs = []
        for index in range(2):
            path = self.scratch / f"text-{index}.txt"
            path.write_text(f"Input {index}.", encoding="utf-8")
            self.inputs.append(BatchInput(path))

        self.model = Model()
        self.model.device = "cpu"
        self.model.sampling_rate = 24000
        self.model.generate = Mock(return_value=[np.array([0.125], dtype=np.float32)])
        self.runtime = ModelLifecycle(Mock(return_value=self.model), Mock())
        self.frame = SimpleNamespace(_models=self.runtime, _=lambda key: key, _BatchProgress=Mock())
        self.preset_prompt = Prompt(Tokens([10, 11], "cpu"), "Saved reference.", 0.3)
        self.prompt_loader = SimpleNamespace(load=Mock(return_value=self.preset_prompt))
        self.seed_scope = Mock(side_effect=lambda seed, device: nullcontext())
        namespace = {
            "Path": Path,
            "PRESETS_DIR": self.presets,
            "safe_child_path": safe_child_path,
            "VoiceClonePrompt": self.prompt_loader,
            "seeded_generation": self.seed_scope,
            "process_text_batch": process_text_batch,
            "operation_error_message": lambda error, translate: str(error),
            "wx": SimpleNamespace(CallAfter=lambda callback, *args: callback(*args)),
        }
        for relative, name in (
            ("omnisonic/app.py", "_GenCloneWorker"),
            ("omnisonic/batch_ui.py", "_GenBatchWorker"),
        ):
            setattr(self.frame, name, load_worker(relative, name, namespace).__get__(self.frame))
        soundfile = ModuleType("soundfile")
        soundfile.write = Mock()
        engine = ModuleType("omnivoice")
        engine.VoiceClonePrompt = self.prompt_loader
        self.modules = patch.dict(sys.modules, {"soundfile": soundfile, "omnivoice": engine})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.batch_sequence = 0

    def clone(self, *, transcript="Reference.", preprocess=True, preset=None, state=None):
        return self.runtime.run(
            state or OperationState(),
            {},
            self.frame._GenCloneWorker,
            SimpleNamespace(preprocess_prompt=preprocess),
            "Synthesize this.",
            str(self.source),
            preset,
            transcript,
            "pl",
            "female",
            1.1,
            None,
            False,
            27,
        )

    def batch(self, *, transcript="Reference.", preprocess=True, preset=None, state=None):
        self.batch_sequence += 1
        kwargs = {"generation_config": SimpleNamespace(preprocess_prompt=preprocess)}
        result = self.runtime.run(
            state or OperationState(),
            {},
            self.frame._GenBatchWorker,
            (0, 1),
            self.scratch / f"output-{self.batch_sequence}",
            kwargs,
            (preset, str(self.source), transcript),
            tuple(self.inputs),
            False,
            27,
        )
        # Worker arguments retained by GUI must not acquire any prompt/tensor.
        self.assertEqual(set(kwargs), {"generation_config"})
        return result

    def test_two_raw_clones_prepare_reference_once_and_preserve_generation_options(self):
        self.clone()
        first = self.model.generate.call_args.kwargs["voice_clone_prompt"]
        self.clone()
        second = self.model.generate.call_args.kwargs["voice_clone_prompt"]
        self.model.create_voice_clone_prompt.assert_called_once_with(
            ref_audio=str(self.source), ref_text="Reference.", preprocess_prompt=True
        )
        self.assertIsNot(first, second)
        self.assertEqual(second.ref_audio_tokens.device.type, "cpu")
        self.assertEqual(self.model.generate.call_args.kwargs["language"], "pl")
        self.assertEqual(self.model.generate.call_args.kwargs["instruct"], "female")
        self.assertEqual(self.model.generate.call_args.kwargs["speed"], 1.1)
        self.seed_scope.assert_called_with(27, "cpu")

    def test_clone_and_batch_share_cache_in_either_order(self):
        for order in ((self.clone, self.batch), (self.batch, self.clone)):
            with self.subTest(order=[worker.__name__ for worker in order]):
                self.runtime.release_model()
                self.model.create_voice_clone_prompt.reset_mock()
                self.model.generate.reset_mock()
                for worker in order:
                    result = worker()
                    if worker == self.batch:
                        self.assertEqual([item.status for item in result], ["done", "done"])
                self.model.create_voice_clone_prompt.assert_called_once()
                self.assertEqual(self.model.generate.call_count, 3)

    def test_presets_bypass_reference_cache_in_both_workers(self):
        self.clone()
        cached = self.runtime._reference_cache._entry
        with patch.object(
            self.runtime._reference_cache,
            "get_or_create",
            wraps=self.runtime._reference_cache.get_or_create,
        ) as lookup:
            self.clone(preset="saved.pt")
            result = self.batch(preset="saved.pt")
            lookup.assert_not_called()
        self.assertEqual([item.status for item in result], ["done", "done"])
        self.assertEqual(self.prompt_loader.load.call_count, 2)
        self.assertIs(
            self.model.generate.call_args.kwargs["voice_clone_prompt"], self.preset_prompt
        )
        self.assertIs(self.runtime._reference_cache._entry, cached)
        self.model.create_voice_clone_prompt.assert_called_once()

    def test_transcript_and_preprocess_changes_invalidate_across_both_workers(self):
        self.clone()
        self.batch(transcript="Other words.")
        self.clone(transcript="Other words.")
        self.batch(transcript="Other words.", preprocess=False)
        self.clone(transcript="Other words.", preprocess=False)
        self.assertEqual(self.model.create_voice_clone_prompt.call_count, 3)
        self.assertEqual(
            [
                call.kwargs["preprocess_prompt"]
                for call in self.model.create_voice_clone_prompt.call_args_list
            ],
            [True, True, False],
        )

    def test_clone_generation_failure_clears_prompt_and_retry_reencodes(self):
        self.model.generate.side_effect = RuntimeError("generation failed")
        with self.assertRaisesRegex(RuntimeError, "generation failed"):
            self.clone()
        self.assertIsNone(self.runtime._reference_cache._entry)
        self.model.generate.side_effect = None
        self.clone()
        self.assertEqual(self.model.create_voice_clone_prompt.call_count, 2)

    def test_cancelled_clone_and_batch_clear_prompt_before_retry(self):
        for worker in (self.clone, self.batch):
            with self.subTest(worker=worker.__name__):
                self.runtime.release_model()
                state = OperationState()

                def cancel(state=state, **kwargs):
                    state.request_cancel()
                    return [np.array([0.125], dtype=np.float32)]

                self.model.generate.side_effect = cancel
                with self.assertRaises(OperationCancelled):
                    worker(state=state)
                self.assertIsNone(self.runtime._reference_cache._entry)
                self.model.generate.side_effect = None
                self.model.create_voice_clone_prompt.reset_mock()
                worker()
                self.model.create_voice_clone_prompt.assert_called_once()

    def test_failed_batch_items_do_not_leave_new_prompt_cached(self):
        self.model.generate.side_effect = RuntimeError("batch generation failed")
        result = self.batch()
        self.assertEqual([item.status for item in result], ["failed", "failed"])
        self.assertIsNone(self.runtime._reference_cache._entry)
        self.model.generate.side_effect = None
        self.model.create_voice_clone_prompt.reset_mock()
        self.clone()
        self.model.create_voice_clone_prompt.assert_called_once()


if __name__ == "__main__":
    unittest.main()
