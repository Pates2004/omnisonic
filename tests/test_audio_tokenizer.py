"""Model-free tests of the official audio tokenizer fallback."""

import ast
import logging
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = "bosonai/higgs-audio-v2-tokenizer"


class AudioTokenizerTests(unittest.TestCase):
    def test_model_prefers_embedded_tokenizer_and_uses_official_fallback(self):
        source = ROOT / "omnivoice/models/omnivoice.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        model_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "OmniVoice"
        )
        method = next(
            node for node in model_class.body if getattr(node, "name", "") == "from_pretrained"
        )
        method.decorator_list = []
        for embedded in (True, False):
            with self.subTest(embedded=embedded):
                resolved = "checkpoint"
                model = SimpleNamespace(device="cpu")
                resolve = Mock(side_effect=[resolved, "remote-tokenizer"])
                tokenizer = Mock()
                extractor = Mock()
                extractor.from_pretrained.return_value.sampling_rate = 24000
                namespace = {
                    "logging": logging,
                    "os": SimpleNamespace(
                        path=SimpleNamespace(
                            join=lambda a, b: a + "/" + b, isdir=Mock(return_value=embedded)
                        )
                    ),
                    "_resolve_model_path": resolve,
                    "super": Mock(
                        return_value=SimpleNamespace(from_pretrained=Mock(return_value=model))
                    ),
                    "AutoTokenizer": Mock(),
                    "AutoFeatureExtractor": extractor,
                    "HiggsAudioV2TokenizerModel": tokenizer,
                    "RuleDurationEstimator": Mock(),
                }
                exec(
                    compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"),
                    namespace,
                )
                self.assertIs(namespace["from_pretrained"](object, "input-model"), model)
                expected_calls = [call("input-model")]
                if not embedded:
                    expected_calls.append(call(OFFICIAL))
                self.assertEqual(resolve.call_args_list, expected_calls)
                expected_path = "checkpoint/audio_tokenizer" if embedded else "remote-tokenizer"
                tokenizer.from_pretrained.assert_called_once_with(expected_path, device_map="cpu")
                extractor.from_pretrained.assert_called_once_with(expected_path)

    def test_data_preparation_defaults_match_inference_fallback(self):
        for script in ("extract_audio_tokens.py", "extract_audio_tokens_add_noise.py"):
            with self.subTest(script=script):
                source = ROOT / "omnivoice" / "scripts" / script
                tree = ast.parse(source.read_text(encoding="utf-8"))
                node = next(
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "--tokenizer_path"
                )
                default = next(kw.value for kw in node.keywords if kw.arg == "default")
                self.assertEqual(ast.literal_eval(default), OFFICIAL)


if __name__ == "__main__":
    unittest.main()
