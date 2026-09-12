"""Model lifetime regressions that also run in CI without GPU libraries."""

import ast
import gc
import unittest
import weakref
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from omnisonic.config import DEFAULT_CONFIG, normalize_config
from omnisonic.model_lifecycle import ModelLifecycle
from omnisonic.operations import OperationState, execute_worker

ROOT = Path(__file__).resolve().parents[1]


class Pipeline:
    def __call__(self, *args, **kwargs):
        return {"text": " transcript "}


class Model:
    sampling_rate = 22050
    _asr_model_name = "whisper-test"
    _asr_pipe = None


def engine_method(name, namespace):
    tree = ast.parse((ROOT / "omnivoice/models/omnivoice.py").read_text(encoding="utf-8"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    method.decorator_list = []
    method.returns = None
    for argument in method.args.args:
        argument.annotation = None
    exec(compile(ast.Module(body=[method], type_ignores=[]), name, "exec"), namespace)
    return namespace[name]


class ModelLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.loaded = []
        self.pipelines = []

        def factory(state):
            model = Model()
            self.loaded.append(weakref.ref(model))
            return model

        self.runtime = ModelLifecycle(factory, gc.collect, lambda cfg: Model())

    def transcribe(self, state, model):
        if model._asr_pipe is None:
            model._asr_pipe = Pipeline()
            self.pipelines.append(weakref.ref(model._asr_pipe))
        if model.unload_asr_after_transcription:
            model._asr_pipe = None
        return "transcript"

    def perform(self, settings, worker=None, transcription=False):
        state = OperationState()
        execute_worker(
            state,
            self.runtime.run_transcription if transcription else self.runtime.run,
            settings,
            worker or self.transcribe,
        )
        self.runtime.collect_if_needed()
        return state

    def test_defaults_and_invalid_values_are_off(self):
        keys = ("unload_asr_after_transcription", "unload_omnivoice_after_operation")
        for key in keys:
            self.assertIs(DEFAULT_CONFIG[key], False)
            self.assertIs(normalize_config({key: "true"})[key], False)
            self.assertIs(normalize_config({key: True})[key], True)

    def test_all_policy_combinations_and_second_use(self):
        for unload_asr in (False, True):
            for unload_main in (False, True):
                with self.subTest(asr=unload_asr, main=unload_main):
                    self.setUp()
                    cfg = dict(
                        unload_asr_after_transcription=unload_asr,
                        unload_omnivoice_after_operation=unload_main,
                    )
                    for _ in range(2):
                        self.assertTrue(self.perform(cfg).succeeded)
                        self.assertEqual(self.runtime.model is None, unload_main)
                        self.assertEqual(self.loaded[-1]() is None, unload_main)
                        self.assertEqual(self.pipelines[-1]() is None, unload_asr)
                    self.assertEqual(len(self.loaded), 2 if unload_main else 1)
                    self.assertEqual(len(self.pipelines), 2 if unload_asr else 1)
                    self.assertEqual(self.runtime.sampling_rate, 22050)

    def test_standalone_transcription_does_not_load_synthesis(self):
        for _ in range(2):
            self.assertTrue(
                self.perform({"unload_asr_after_transcription": True}, transcription=True).succeeded
            )
            self.assertIsNone(self.runtime.asr_pipe)
        self.assertFalse(self.loaded)
        self.assertEqual(len(self.pipelines), 2)

    def test_standalone_asr_cache_is_reused_by_synthesis(self):
        self.perform({}, transcription=True)
        pipe = self.runtime.asr_pipe
        self.perform({})
        self.assertIs(self.runtime.model._asr_pipe, pipe)
        self.assertIsNone(self.runtime.asr_pipe)
        self.assertEqual(len(self.pipelines), 1)

    def test_model_is_retained_for_whole_batch(self):
        def batch(state, model):
            for _ in range(3):
                self.assertIs(self.runtime.model, model)
                self.transcribe(state, model)
            return ["one.wav", "two.wav", "three.wav"]

        result = self.perform({"unload_omnivoice_after_operation": True}, batch)
        self.assertEqual(len(result.result), 3)
        self.assertEqual(len(self.loaded), 1)
        self.assertIsNone(self.loaded[0]())

    def test_errors_and_cancellation_do_not_retain_model_in_tracebacks(self):
        for fail in (False, True):

            def worker(state, model, fail=fail):
                self.transcribe(state, model)
                if fail:
                    try:
                        raise ValueError("inner failure")
                    except ValueError as exc:
                        raise RuntimeError("outer failure") from exc
                state.request_cancel()
                state.check_cancelled()

            cfg = dict(unload_asr_after_transcription=True, unload_omnivoice_after_operation=True)
            if fail:
                with self.assertLogs("omnisonic.operations", level="ERROR"):
                    result = self.perform(cfg, worker)
                self.assertEqual(str(result.error), "outer failure")
            else:
                self.assertTrue(self.perform(cfg, worker).cancel_flag)
            self.assertTrue(all(ref() is None for ref in self.loaded + self.pipelines))

    def test_cancelled_before_loading_does_not_download_or_load(self):
        state = OperationState()
        state.request_cancel()
        execute_worker(state, self.runtime.run, {}, self.transcribe)
        self.assertFalse(self.loaded)

    def test_failed_loading_can_be_retried(self):
        good_factory = self.runtime.factory

        def bad_factory(state):
            model = good_factory(state)
            assert model is not None
            raise RuntimeError("load failed")

        self.runtime.factory = bad_factory
        with self.assertLogs("omnisonic.operations", level="ERROR"):
            self.assertIsNotNone(self.perform({"unload_omnivoice_after_operation": True}).error)
        self.assertIsNone(self.loaded[0]())
        self.runtime.factory = good_factory
        self.assertTrue(self.perform({}).succeeded)

    def test_asr_model_change_invalidates_detached_cache(self):
        self.perform({"asr_model_name": "first"}, transcription=True)
        first = self.pipelines[0]
        self.perform({"asr_model_name": "second"}, transcription=True)
        gc.collect()
        self.assertIsNone(first())
        self.assertEqual(len(self.pipelines), 2)

    def test_explicit_unload_releases_both_models(self):
        self.perform({})
        self.runtime.release_all()
        self.runtime.collect_if_needed()
        self.assertTrue(all(ref() is None for ref in self.loaded + self.pipelines))

    def test_tokenizer_lru_cache_cannot_retain_released_model_weights(self):
        class Tokenizer:
            @lru_cache  # noqa: B019 - deliberately reproduce the upstream retention bug
            def _get_conv1d_layers(self, module):
                return (module,)

        self.perform({})
        self.runtime.model.audio_tokenizer = Tokenizer()
        tokenizer = self.runtime.model.audio_tokenizer
        tokenizer._get_conv1d_layers(tokenizer)
        reference = weakref.ref(tokenizer)
        method = engine_method("release_inference_caches", {})
        self.runtime.model.release_inference_caches = method.__get__(self.runtime.model)
        del tokenizer
        self.runtime.release_all()
        self.runtime.collect_if_needed()
        self.assertIsNone(reference())
        self.assertIsNone(self.loaded[-1]())


class WhisperLifetimeTests(unittest.TestCase):
    def test_engine_releases_immediately_on_success_and_error(self):
        transcribe = engine_method("transcribe", {})
        for unload in (False, True):
            for fail in (False, True):
                holder = Model()
                holder.unload_asr_after_transcription = unload
                holder._asr_pipe = (
                    Pipeline() if not fail else Mock(side_effect=ValueError("bad ASR"))
                )
                holder.unload_asr_model = lambda holder=holder: setattr(holder, "_asr_pipe", None)
                if fail:
                    with self.assertRaisesRegex(ValueError, "bad ASR"):
                        transcribe(holder, "audio.wav")
                else:
                    self.assertEqual(transcribe(holder, "audio.wav"), "transcript")
                self.assertEqual(holder._asr_pipe is None, unload)

    def test_unload_drops_pipeline_before_releasing_device_memory(self):
        holder = SimpleNamespace(_asr_pipe=Pipeline(), _asr_device="xpu:0")
        release = Mock(side_effect=lambda *args: self.assertIsNone(holder._asr_pipe))
        unload = engine_method("unload_asr_model", {"release_memory": release, "torch": "torch"})
        unload(holder)
        release.assert_called_once_with("xpu:0", "torch")

    def test_cpu_cuda_rocm_xpu_cleanup_uses_only_initialized_device(self):
        namespace = {}
        exec((ROOT / "omnivoice/utils/memory.py").read_text(encoding="utf-8"), namespace)
        for device in ("cpu", "cuda:0", "xpu:0"):
            for initialized in (False, True):
                backend = MagicMock()
                backend.is_initialized.return_value = initialized
                fake_torch = SimpleNamespace(cuda=backend, xpu=backend)
                namespace["release_memory"](device, fake_torch)
                if device != "cpu" and initialized:
                    backend.device.assert_called_once_with(device)
                    backend.empty_cache.assert_called_once()
                else:
                    backend.empty_cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()
