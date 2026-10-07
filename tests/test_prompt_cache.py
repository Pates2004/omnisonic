"""Reference prompt reuse without real models, user audio or mandatory Torch."""

import gc
import importlib.util
import os
import tempfile
import unittest
import weakref
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from omnisonic.operations import OperationCancelled, OperationState
from omnisonic.prompt_cache import ReferencePromptCache, _file_version


ROOT = Path(__file__).resolve().parents[1]


class Tokens:
    def __init__(self, values, device="cuda:0"):
        self.values = list(values)
        self.device = SimpleNamespace(type=device)

    def numel(self):
        return len(self.values)

    def element_size(self):
        return 8

    def detach(self):
        return self

    def cpu(self):
        return self if self.device.type == "cpu" else Tokens(self.values, "cpu")

    def clone(self):
        return Tokens(self.values, self.device.type)


@dataclass
class Prompt:
    ref_audio_tokens: Tokens
    ref_text: str
    ref_rms: float

    def validate(self):
        if not isinstance(self.ref_text, str):
            raise ValueError("invalid prompt")


class Model:
    def __init__(self):
        self.create_voice_clone_prompt = Mock(
            side_effect=lambda **kwargs: Prompt(
                Tokens([1, 2, 3]), kwargs["ref_text"] or "automatic transcript", 0.25
            )
        )


class PromptCacheTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "trash").mkdir(exist_ok=True)
        self.scratch = Path(tempfile.mkdtemp(prefix="prompt-cache-", dir=ROOT / "trash"))
        self.source = self.scratch / "synthetic-reference.bin"
        self.source.write_bytes(b"synthetic audio")
        self.cache = ReferencePromptCache()
        self.model = Model()
        self.state = OperationState()

    def obtain(self, **kwargs):
        arguments = dict(source=self.source, transcript="Reference.", asr_identity=("asr", "cpu"))
        arguments.update(kwargs)
        return self.cache.get_or_create(self.state, self.model, **arguments)

    def test_same_reference_reuses_encoding_with_independent_cpu_tokens(self):
        original = self.obtain()
        self.assertEqual(original.ref_audio_tokens.device.type, "cuda:0")
        stored = self.cache._entry.prompt
        self.assertEqual(stored.ref_audio_tokens.device.type, "cpu")
        self.assertIsNot(stored.ref_audio_tokens, original.ref_audio_tokens)
        original.ref_audio_tokens.values[0] = 91
        original.ref_text = "Changed by caller"
        cached = self.obtain()
        self.assertEqual(cached.ref_audio_tokens.values, [1, 2, 3])
        self.assertEqual(cached.ref_text, "Reference.")
        self.assertEqual(cached.ref_rms, 0.25)
        self.assertIs(type(cached), Prompt)
        self.assertIsNot(cached, stored)
        self.assertIsNot(cached.ref_audio_tokens, stored.ref_audio_tokens)
        cached.ref_audio_tokens.values[1] = 72
        cached.ref_rms = 0.9
        self.assertEqual(self.obtain().ref_audio_tokens.values, [1, 2, 3])
        self.assertEqual(self.obtain().ref_rms, 0.25)
        self.model.create_voice_clone_prompt.assert_called_once_with(
            ref_audio=self.source, ref_text="Reference.", preprocess_prompt=True
        )

    def test_cpu_encoder_result_is_copied_not_shared(self):
        original = Prompt(Tokens([4, 5], "cpu"), "CPU.", 0.1)
        self.model.create_voice_clone_prompt.side_effect = None
        self.model.create_voice_clone_prompt.return_value = original
        self.obtain()
        original.ref_audio_tokens.values[0] = 99
        self.assertEqual(self.obtain().ref_audio_tokens.values, [4, 5])

    def test_content_change_is_detected_when_size_and_timestamps_are_preserved(self):
        # Even a filesystem reporting identical metadata must not produce a hit.
        with patch("omnisonic.prompt_cache._file_version", return_value=("same metadata",)):
            self.obtain()
            info = self.source.stat()
            self.source.write_bytes(b"different audio")
            os.utime(self.source, ns=(info.st_atime_ns, info.st_mtime_ns))
            self.assertEqual(self.source.stat().st_size, info.st_size)
            self.obtain()
        self.assertEqual(self.model.create_voice_clone_prompt.call_count, 2)

    def test_path_alias_resolves_to_same_file(self):
        self.obtain()
        self.obtain(source=str(self.source.parent / "." / self.source.name))
        self.model.create_voice_clone_prompt.assert_called_once()

    def test_file_version_ignores_inconsistent_windows_ctime_semantics(self):
        stat_info = dict(st_dev=7, st_ino=8, st_size=10, st_mtime_ns=123)
        self.assertEqual(
            _file_version(SimpleNamespace(**stat_info, st_ctime_ns=1)),
            _file_version(SimpleNamespace(**stat_info, st_ctime_ns=999)),
        )

    def test_non_regular_source_does_not_get_opened_by_cache(self):
        with patch("omnisonic.prompt_cache.Path.open") as open_file:
            self.obtain(source=self.scratch)
        open_file.assert_not_called()
        self.assertIsNone(self.cache._entry)

    def test_non_weak_referenceable_model_is_not_kept_alive_in_cache(self):
        self.model = SimpleNamespace(create_voice_clone_prompt=self.model.create_voice_clone_prompt)
        self.obtain()
        self.obtain()
        self.assertIsNone(self.cache._entry)
        self.assertEqual(self.model.create_voice_clone_prompt.call_count, 2)

    def test_source_text_preprocessing_and_asr_identity_invalidate_entry(self):
        second = self.scratch / "other-reference.bin"
        second.write_bytes(self.source.read_bytes())
        for arguments in (
            {},
            {"source": second},
            {"source": second, "transcript": "Different."},
            {"source": second, "transcript": "Different.", "preprocess_prompt": False},
            {
                "source": second,
                "transcript": "Different.",
                "preprocess_prompt": False,
                "asr_identity": ("other-asr", "cpu"),
            },
        ):
            self.obtain(**arguments)
            self.obtain(**arguments)
        self.assertEqual(self.model.create_voice_clone_prompt.call_count, 5)

    def test_blank_manual_transcript_does_not_match_automatic_transcription(self):
        self.obtain(transcript=None)
        self.obtain(transcript="")
        self.assertEqual(self.model.create_voice_clone_prompt.call_count, 2)

    def test_cache_does_not_retain_model_and_new_instance_cannot_hit(self):
        self.obtain()
        old = weakref.ref(self.model)
        self.model = Model()
        gc.collect()
        self.assertIsNone(old())
        self.obtain()
        self.model.create_voice_clone_prompt.assert_called_once()

    def test_source_replaced_during_encoding_is_not_cached(self):
        create = self.model.create_voice_clone_prompt.side_effect

        def changing(**kwargs):
            self.source.write_bytes(b"changed during encoding")
            return create(**kwargs)

        self.model.create_voice_clone_prompt.side_effect = changing
        self.obtain()
        self.assertIsNone(self.cache._entry)
        self.model.create_voice_clone_prompt.side_effect = create
        self.obtain()
        self.assertIsNotNone(self.cache._entry)
        self.assertEqual(self.model.create_voice_clone_prompt.call_count, 2)

    def test_missing_source_keeps_normal_encoder_error_and_clears_old_entry(self):
        self.obtain()
        self.model.create_voice_clone_prompt.side_effect = FileNotFoundError("reference missing")
        with self.assertRaisesRegex(FileNotFoundError, "reference missing"):
            self.obtain(source=self.scratch / "missing.bin")
        self.assertIsNone(self.cache._entry)

    def test_cache_io_problem_does_not_prevent_normal_encoding(self):
        with patch("omnisonic.prompt_cache.Path.open", side_effect=PermissionError("hash denied")):
            self.obtain()
            self.obtain()
        self.model.create_voice_clone_prompt.assert_called()
        self.assertEqual(self.model.create_voice_clone_prompt.call_count, 2)
        self.assertIsNone(self.cache._entry)

    def test_cancellation_during_hashing_does_not_encode_or_retain_cache(self):
        self.obtain()
        self.model.create_voice_clone_prompt.reset_mock()
        checks = 0
        original_check = self.state.check_cancelled

        def cancel_in_hash():
            nonlocal checks
            checks += 1
            if checks == 4:
                self.state.request_cancel()
            original_check()

        with (
            patch("omnisonic.prompt_cache._HASH_CHUNK_BYTES", 4),
            patch.object(self.state, "check_cancelled", side_effect=cancel_in_hash),
            self.assertRaises(OperationCancelled),
        ):
            self.obtain()
        self.model.create_voice_clone_prompt.assert_not_called()
        self.assertIsNone(self.cache._entry)

    def test_encoder_failure_and_cancellation_never_populate_cache(self):
        create = self.model.create_voice_clone_prompt.side_effect
        self.model.create_voice_clone_prompt.side_effect = RuntimeError("encoder failed")
        with self.assertRaisesRegex(RuntimeError, "encoder failed"):
            self.obtain()
        self.assertIsNone(self.cache._entry)

        def cancel_after_encode(**kwargs):
            self.state.request_cancel()
            return create(**kwargs)

        self.model.create_voice_clone_prompt.side_effect = cancel_after_encode
        with self.assertRaises(OperationCancelled):
            self.obtain()
        self.assertIsNone(self.cache._entry)

    def test_invalid_and_oversized_prompt_are_not_cached(self):
        self.cache = ReferencePromptCache(max_token_bytes=8)
        self.obtain()
        self.obtain()
        self.assertIsNone(self.cache._entry)
        self.assertEqual(self.model.create_voice_clone_prompt.call_count, 2)
        self.cache = ReferencePromptCache()
        self.model.create_voice_clone_prompt.side_effect = None
        self.model.create_voice_clone_prompt.return_value = Prompt(Tokens([1]), None, 0.1)
        with self.assertRaisesRegex(ValueError, "invalid prompt"):
            self.obtain()
        self.assertIsNone(self.cache._entry)

    def test_clear_releases_prompt_storage(self):
        self.obtain()
        stored = weakref.ref(self.cache._entry.prompt.ref_audio_tokens)
        self.cache.clear()
        gc.collect()
        self.assertIsNone(stored())
        self.obtain()
        self.assertEqual(self.model.create_voice_clone_prompt.call_count, 2)

    @unittest.skipUnless(importlib.util.find_spec("torch"), "Optional real CPU tensor validation")
    def test_real_engine_prompt_type_and_tensor_storage_are_preserved(self):
        import torch

        from tests.test_inference_validation import engine_namespace

        prompt_type = engine_namespace(torch)["VoiceClonePrompt"]
        tokens = torch.arange(16).reshape(8, 2)
        original = prompt_type(tokens, "Transcript.", 0.2)
        self.model.create_voice_clone_prompt.side_effect = None
        self.model.create_voice_clone_prompt.return_value = original
        self.obtain()
        stored = self.cache._entry.prompt
        self.assertIs(type(stored), prompt_type)
        self.assertEqual(stored.ref_audio_tokens.device.type, "cpu")
        self.assertNotEqual(stored.ref_audio_tokens.data_ptr(), tokens.data_ptr())
        tokens.fill_(9)
        cached = self.obtain()
        self.assertTrue(torch.equal(cached.ref_audio_tokens, torch.arange(16).reshape(8, 2)))
        self.assertNotEqual(cached.ref_audio_tokens.data_ptr(), stored.ref_audio_tokens.data_ptr())
        cached.validate()


if __name__ == "__main__":
    unittest.main()
