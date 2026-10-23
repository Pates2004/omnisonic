"""Denoiser tensor-batch contracts without importing model or dataset libraries."""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


class Tensor:
    """Small NumPy-backed tensor for the processor's CPU-only shape contracts."""

    def __init__(self, values):
        self.values = np.asarray(values)

    @property
    def shape(self):
        return self.values.shape

    def __iter__(self):
        return (Tensor(value) for value in self.values)

    def __getitem__(self, index):
        return Tensor(self.values[index])

    def view(self, *shape):
        return Tensor(self.values.reshape(shape))

    def transpose(self, first, second):
        return Tensor(self.values.swapaxes(first, second))

    def to(self, device):
        return self

    def cpu(self):
        return self

    def contiguous(self):
        return Tensor(np.ascontiguousarray(self.values))


def tensor_pad(tensor, padding):
    if not isinstance(tensor, Tensor):
        raise TypeError("pad input must be a Tensor, not a list")
    widths = [(0, 0)] * len(tensor.shape)
    widths[-1] = padding
    return Tensor(np.pad(tensor.values, widths))


def tensor_unsqueeze(tensor, dim):
    return Tensor(np.expand_dims(tensor.values, axis=dim))


def load_processor(torch_module):
    source = ROOT / "omnivoice/scripts/denoise_audio.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    processor = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SpeechDenoisingProcessor"
    )
    methods = [
        node
        for node in processor.body
        if isinstance(node, ast.FunctionDef) and node.name in {"process", "process_batch"}
    ]
    for method in methods:
        method.decorator_list = []
    processor.body = methods
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
        + [processor],
        type_ignores=[],
    )
    features = Mock()
    namespace = {
        "torch": torch_module,
        "SIDON_OUTPUT_SAMPLE_RATE": 48000,
        "extract_seamless_m4t_features": features,
    }
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
    return namespace["SpeechDenoisingProcessor"](), features


class DenoiseProcessorTests(unittest.TestCase):
    def setUp(self):
        self.torch = SimpleNamespace(
            unsqueeze=Mock(side_effect=tensor_unsqueeze),
            nn=SimpleNamespace(functional=SimpleNamespace(pad=Mock(side_effect=tensor_pad))),
        )
        self.processor, self.features = load_processor(self.torch)
        self.processor.device = "cpu"
        self.features.return_value = {"input_features": Tensor(np.zeros((2, 3, 4)))}
        self.processor.feature_extractor = Mock(
            return_value={"last_hidden_state": Tensor(np.zeros((2, 3, 4)))}
        )
        self.processor.decoder = Mock(return_value=Tensor(np.arange(12).reshape(2, 6)))

    def test_single_waveform_gets_one_tensor_batch_dimension(self):
        waveform = Tensor(np.array([0.1, -0.2, 0.3], dtype=np.float32))
        output = object()
        self.processor.process_batch = Mock(return_value=[output])

        self.assertIs(self.processor.process(waveform, 16000), output)

        self.torch.unsqueeze.assert_called_once_with(waveform, dim=0)
        batch, sample_rates = self.processor.process_batch.call_args.args
        self.assertIsInstance(batch, Tensor)
        self.assertEqual(batch.shape, (1, 3))
        self.assertEqual(sample_rates, [16000])
        np.testing.assert_array_equal(batch.values[0], waveform.values)

    def test_single_waveform_reaches_padding_and_restores_sample_rate_length(self):
        waveform = Tensor(np.array([0.5, -0.25, 0.0, 0.25], dtype=np.float32))
        original = waveform.values.copy()
        self.features.return_value = {"input_features": Tensor(np.zeros((1, 3, 4)))}
        self.processor.feature_extractor.return_value = {
            "last_hidden_state": Tensor(np.zeros((1, 3, 4)))
        }
        self.processor.decoder.return_value = Tensor(np.arange(16).reshape(1, 16))

        output = self.processor.process(waveform, 16000)

        self.assertEqual(output.shape, (12,))
        np.testing.assert_array_equal(output.values, np.arange(12))
        np.testing.assert_array_equal(waveform.values, original)
        padded = self.features.call_args.args[0]
        self.assertEqual(len(padded), 1)
        self.assertEqual(padded[0].shape, (24004,))
        np.testing.assert_array_equal(padded[0].values[:4], original)
        np.testing.assert_array_equal(padded[0].values[4:], 0)

    def test_existing_tensor_batch_preserves_per_item_sample_rates(self):
        waveforms = Tensor(np.ones((2, 4), dtype=np.float32))

        outputs = self.processor.process_batch(waveforms, [48000, 24000])

        self.torch.unsqueeze.assert_not_called()
        self.assertEqual([output.shape for output in outputs], [(4,), (8,)])
        np.testing.assert_array_equal(outputs[0].values, [0, 1, 2, 3])
        np.testing.assert_array_equal(outputs[1].values, [6, 7, 8, 9, 10, 11, 0, 0])
        padded = self.features.call_args.args[0]
        self.assertEqual([item.shape for item in padded], [(24004,), (24004,)])

    def test_explicit_lengths_do_not_require_sample_rates(self):
        outputs = self.processor.process_batch(Tensor(np.ones((2, 4))), expected_lengths=[2, 7])

        self.assertEqual([output.shape for output in outputs], [(2,), (7,)])
        np.testing.assert_array_equal(outputs[0].values, [0, 1])
        np.testing.assert_array_equal(outputs[1].values, [6, 7, 8, 9, 10, 11, 0])

    def test_missing_sample_rates_fail_before_feature_or_model_calls(self):
        with self.assertRaisesRegex(ValueError, "sample_rates is required"):
            self.processor.process_batch(Tensor(np.ones((2, 4))))

        self.torch.nn.functional.pad.assert_not_called()
        self.features.assert_not_called()
        self.processor.feature_extractor.assert_not_called()
        self.processor.decoder.assert_not_called()

    def test_mismatched_sample_rate_count_is_not_silently_truncated(self):
        with self.assertRaises(ValueError):
            self.processor.process_batch(Tensor(np.ones((2, 4))), [16000])

        self.torch.nn.functional.pad.assert_not_called()
        self.features.assert_not_called()


if __name__ == "__main__":
    unittest.main()
