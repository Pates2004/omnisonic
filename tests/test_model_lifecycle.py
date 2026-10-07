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
from omnisonic.operations import OperationCancelled, OperationState, execute_worker

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

        def factory(state, settings):
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

    def test_loader_receives_the_operations_settings_snapshot(self):
        settings = {"asr_model_name": "first", "preload_asr": False}
        self.runtime.factory = Mock(return_value=Model())
        state = OperationState()
        self.runtime.ensure(state, settings)
        self.runtime.factory.assert_called_once_with(state, settings)

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

    def test_reference_prompt_forwards_model_and_asr_identity(self):
        self.runtime._reference_cache = Mock()
        state = OperationState()
        model = self.runtime.ensure(state, {"asr_model_name": "selected-asr"})
        result = self.runtime.reference_prompt(state, model, "reference.wav", None, False)
        self.runtime._reference_cache.get_or_create.assert_called_once_with(
            state,
            model,
            "reference.wav",
            None,
            False,
            asr_identity=("selected-asr", "whisper-test", "None"),
        )
        self.assertIs(result, self.runtime._reference_cache.get_or_create.return_value)

    def test_reference_cache_clears_when_asr_configuration_changes(self):
        self.runtime._reference_cache = Mock()
        self.runtime.ensure(OperationState(), {"asr_model_name": "first"})
        self.runtime.configure_asr({"asr_model_name": "first"})
        self.runtime._reference_cache.reset_mock()
        self.runtime.configure_asr({"asr_model_name": "first"})
        self.runtime._reference_cache.clear.assert_not_called()
        self.runtime.configure_asr({"asr_model_name": "second"})
        self.runtime._reference_cache.clear.assert_called()

    def test_reference_cache_survives_success_but_not_failure_or_cancellation(self):
        self.runtime._reference_cache = Mock()
        state = OperationState()
        self.assertEqual(self.runtime.run(state, {}, lambda state, model: "done"), "done")
        self.runtime._reference_cache.clear.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "generation failed"):
            self.runtime.run(state, {}, Mock(side_effect=RuntimeError("generation failed")))
        self.runtime._reference_cache.clear.assert_called_once()
        self.runtime._reference_cache.reset_mock()

        def late_cancel(state, model):
            state.request_cancel()
            return "discarded"

        with self.assertRaises(OperationCancelled):
            self.runtime.run(state, {}, late_cancel)
        self.runtime._reference_cache.clear.assert_called_once()

    def test_reference_cache_is_cleared_on_model_release_including_empty_runtime(self):
        self.runtime._reference_cache = Mock()
        self.runtime.release_model()
        self.runtime._reference_cache.clear.assert_called_once()
        self.runtime._reference_cache.reset_mock()
        self.runtime.run(
            OperationState(), {"unload_omnivoice_after_operation": True}, lambda state, model: None
        )
        self.runtime._reference_cache.clear.assert_called_once()
        self.runtime._reference_cache.reset_mock()
        self.runtime.release_all()
        self.runtime._reference_cache.clear.assert_called_once()

    def test_asr_memory_unload_does_not_invalidate_unchanged_reference(self):
        self.runtime._reference_cache = Mock()
        self.runtime.run(
            OperationState(), {"unload_asr_after_transcription": True}, lambda state, model: None
        )
        self.runtime._reference_cache.clear.assert_not_called()

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

        def bad_factory(state, settings):
            model = good_factory(state, settings)
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

    def test_empty_runtime_cleanup_does_not_report_model_release(self):
        self.runtime.release_all()
        self.assertTrue(self.runtime.needs_collection)
        self.assertIs(self.runtime.collect_if_needed(), False)

    def test_actual_model_release_is_reported_once_after_collection(self):
        self.perform({})
        self.runtime.release_all()
        self.assertIs(self.runtime.collect_if_needed(), True)
        self.assertIs(self.runtime.collect_if_needed(), False)

    def test_asr_only_release_does_not_report_synthesis_model_release(self):
        self.perform({}, transcription=True)
        self.runtime.release_asr()
        self.assertIs(self.runtime.collect_if_needed(), False)

    def test_failed_model_load_does_not_log_successful_unload_in_gui(self):
        from omnisonic.validation import operation_error_message

        self.runtime.factory = Mock(side_effect=FileNotFoundError(2, "No such file or directory"))
        tree = ast.parse((ROOT / "omnisonic/app.py").read_text(encoding="utf-8"))
        names = {"_EnsureModelWorker", "_complete_operation"}
        methods = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name in names
        ]
        wx = Mock(OK=1, ICON_ERROR=2)
        namespace = {"wx": wx, "operation_error_message": operation_error_message}
        exec(
            compile(ast.Module(body=methods, type_ignores=[]), "startup-handlers", "exec"),
            namespace,
        )
        frame = SimpleNamespace(
            _models=self.runtime,
            model=None,
            btn_toggle_model=Mock(),
            Log=Mock(),
            _=lambda key: key,
            _MaybeAutoTranscribeReference=Mock(),
        )
        with self.assertLogs("omnisonic.operations", level="ERROR"):
            state = execute_worker(
                OperationState(), namespace["_EnsureModelWorker"].__get__(frame), {}
            )
        namespace["_complete_operation"](frame, state, None)
        self.assertIsInstance(state.error, FileNotFoundError)
        frame.Log.assert_called_once_with("msg_error[Errno 2] No such file or directory")
        wx.MessageBox.assert_called_once()

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
