"""Seed dispatch, worker boundaries and preferences without importing wx or torch."""

from __future__ import annotations

import ast
import inspect
import logging
import sys
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import numpy as np

from omnisonic.batch import BatchInput
from omnisonic.config import DEFAULT_CONFIG
from omnisonic.operations import OperationCancelled, OperationState
from omnisonic.validation import (
    normalize_pasted_path,
    operation_error_message,
    output_directory_path,
    validation_error_message,
)


ROOT = Path(__file__).resolve().parents[1]


def handler(name, **namespace):
    filename = "batch_ui.py" if name in {"OnGenBatch", "_GenBatchWorker"} else "app.py"
    tree = ast.parse((ROOT / "omnisonic" / filename).read_text(encoding="utf-8"))
    node = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


class GenerationSeedDispatchTests(unittest.TestCase):
    def test_disabled_zero_and_maximum_seed_are_forwarded_by_all_modes(self):
        for method in ("OnGenClone", "OnGenAuto", "OnGenDesign", "OnGenBatch"):
            for enabled, value in ((False, 123), (True, 0), (True, 2147483647)):
                with self.subTest(method=method, enabled=enabled, seed=value):
                    frame = Mock(cfg={})
                    frame._.side_effect = lambda key: key
                    frame._CanUseModel.return_value = True
                    frame._CheckTextNormalization.return_value = True
                    frame.chk_seed.GetValue.return_value = enabled
                    frame.spin_seed.GetValue.return_value = value
                    frame._GetGenerationSeed = handler("_GetGenerationSeed").__get__(frame)
                    for mode in ("clone", "auto", "design"):
                        getattr(frame, mode + "_text").GetValue.return_value = "Synthetic text"
                        getattr(frame, mode + "_lang").GetValue.return_value = "English"
                    frame.design_combos = []
                    frame.design_custom_instruct.GetValue.return_value = "Soft voice"
                    frame.clone_ref_audio.GetValue.return_value = "synthetic.wav"
                    frame.clone_ref_text.GetValue.return_value = "Reference"
                    frame.clone_instruct.GetValue.return_value = ""
                    frame.combo_presets.GetSelection.return_value = -1
                    frame.batch_items = [
                        SimpleNamespace(status="pending", source="input.txt", source_root=None)
                    ]
                    frame.batch_mode.GetSelection.return_value = 2
                    frame.batch_output.GetValue.return_value = "synthetic-output"
                    wx = Mock(NOT_FOUND=-1)
                    handler(
                        method,
                        wx=wx,
                        os=SimpleNamespace(path=SimpleNamespace(exists=lambda path: True)),
                        Path=Path,
                        datetime=datetime,
                        uuid4=uuid4,
                        BatchInput=BatchInput,
                        normalize_pasted_path=normalize_pasted_path,
                        output_directory_path=output_directory_path,
                        validation_error_message=validation_error_message,
                        default_audio_directory=lambda kind: Path("synthetic-output"),
                    )(frame, None)
                    frame.RunModelOperation.assert_called_once()
                    self.assertEqual(
                        frame.RunModelOperation.call_args.args[-1], value if enabled else None
                    )
                    wx.MessageBox.assert_not_called()


class GenerationSeedWorkerTests(unittest.TestCase):
    def exercise(self, method, seed, *, fail=False, cancelled=False, cached_reference=False):
        active = []
        entries = []
        exits = []

        @contextmanager
        def seeded_generation(value, device):
            self.assertEqual(active, [])
            entries.append((value, device))
            active.append(value)
            try:
                yield
            finally:
                exits.append(active.pop())

        def generate(**kwargs):
            self.assertEqual(active, [seed])
            self.assertNotIn("seed", kwargs)
            if fail:
                raise RuntimeError("Synthetic generation failure")
            return [np.zeros(16, dtype=np.float32)]

        def reference_prompt(*args, **kwargs):
            self.assertEqual(active, [], "Reference preparation must not consume generation RNG")
            return object()

        frame = Mock()
        frame._.side_effect = lambda key: key
        frame._models.reference_prompt.side_effect = reference_prompt
        model = SimpleNamespace(
            device="cuda:0", sampling_rate=24000, generate=Mock(side_effect=generate)
        )
        state = OperationState()
        if cancelled:
            state.request_cancel()
        generation_config = SimpleNamespace(preprocess_prompt=True)

        def process_batch(inputs, output, state, synthesize, save, progress, **kwargs):
            return [synthesize(text) for text in ("First", "Second")]

        namespace = dict(
            seeded_generation=seeded_generation,
            Path=Path,
            wx=Mock(),
            process_text_batch=process_batch,
            operation_error_message=operation_error_message,
        )
        function = handler(method, **namespace)
        values = dict(
            self=frame,
            state=state,
            model=model,
            gen_config=generation_config,
            text="Synthetic text",
            ref_audio="reference.wav",
            preset_path=None,
            ref_text="Reference",
            lang="English",
            instruct="Soft voice",
            speed=1.0,
            duration=None,
            norm_txt=False,
            seed=seed,
            indices=(0, 1),
            output=Path("unused-output"),
            kwargs={"generation_config": generation_config},
            prompt_source=(None, "reference.wav", "Reference") if cached_reference else None,
            inputs=(),
            preserve_structure=True,
        )
        arguments = {name: values[name] for name in inspect.signature(function).parameters}
        with patch.dict(
            sys.modules,
            {"soundfile": Mock(), "omnivoice": SimpleNamespace(VoiceClonePrompt=Mock())},
        ):
            if cancelled:
                with self.assertRaises(OperationCancelled):
                    function(**arguments)
            elif fail:
                with self.assertRaisesRegex(RuntimeError, "Synthetic generation failure"):
                    function(**arguments)
            else:
                function(**arguments)
        self.assertEqual(active, [])
        expected_count = 0 if cancelled else 2 if method == "_GenBatchWorker" and not fail else 1
        self.assertEqual(entries, [(seed, model.device)] * expected_count)
        self.assertEqual(exits, [seed] * expected_count)
        self.assertEqual(model.generate.call_count, expected_count)

    def test_seed_scope_wraps_generation_in_every_mode_and_each_batch_item(self):
        for method in ("_GenCloneWorker", "_GenAutoWorker", "_GenDesignWorker", "_GenBatchWorker"):
            for seed in (None, 0, 123):
                with self.subTest(method=method, seed=seed):
                    self.exercise(method, seed, cached_reference=True)

    def test_generation_failure_exits_scope_and_prior_cancellation_never_enters(self):
        for method in ("_GenCloneWorker", "_GenAutoWorker", "_GenDesignWorker", "_GenBatchWorker"):
            for cancelled in (False, True):
                with self.subTest(method=method, cancelled=cancelled):
                    self.exercise(method, 42, fail=not cancelled, cancelled=cancelled)


class SeedControl:
    def __init__(self, parent=None, value=0, **kwargs):
        self.value = int(value) if isinstance(value, str) and value.isdecimal() else value
        self.enabled = True
        self.name = ""
        self.callback = None

    def SetValue(self, value):
        self.value = value

    def GetValue(self):
        return self.value

    def Enable(self, value=True):
        self.enabled = value

    def Disable(self):
        self.Enable(False)

    def SetName(self, name):
        self.name = name

    def SetToolTip(self, text):
        pass

    def GetChildren(self):
        return []

    def Bind(self, event, callback):
        self.callback = callback

    def Clear(self):
        self.value = ""


class GenerationSeedPreferenceTests(unittest.TestCase):
    def controls(self, **settings):
        wx = MagicMock()
        for kind in ("SpinCtrl", "SpinCtrlDouble", "CheckBox"):
            getattr(wx, kind).side_effect = SeedControl
        parent = SimpleNamespace(cfg=dict(DEFAULT_CONFIG, **settings), _=lambda key: key)
        handler("SetupAdvTab", wx=wx, AccessibleFloatCtrl=SeedControl)(parent, Mock())
        parent.clone_instruct = SeedControl(value="")
        parent.design_custom_instruct = SeedControl(value="")
        return parent

    def test_seed_controls_obey_remember_setting_and_toggle_enabled_state(self):
        for remember in (False, True):
            with self.subTest(remember=remember):
                parent = self.controls(
                    remember_ai_settings=remember, use_fixed_seed=True, ai_seed=42
                )
                self.assertEqual(parent.chk_seed.GetValue(), remember)
                self.assertEqual(parent.spin_seed.GetValue(), 42 if remember else 0)
                self.assertEqual(parent.spin_seed.enabled, remember)
                self.assertEqual(parent.chk_seed.name, "use_fixed_seed")
                self.assertEqual(parent.spin_seed.name, "seed_value")
                parent.chk_seed.SetValue(not remember)
                parent.chk_seed.callback(None)
                self.assertEqual(parent.spin_seed.enabled, not remember)

    def test_reset_and_cancelled_settings_preview_restore_seed_state(self):
        for reset in ("OnResetAI", "OnResetApp"):
            with self.subTest(reset=reset):
                parent = self.controls(use_fixed_seed=True, ai_seed=42)
                dialog = Mock(cfg=dict(DEFAULT_CONFIG, use_fixed_seed=True, ai_seed=42))
                dialog.GetParent.return_value = parent
                dialog._.side_effect = lambda key: key
                dialog.avail_langs = [DEFAULT_CONFIG["language"]]
                dialog._initial_parent_ai_state = handler("_capture_parent_ai_state")(dialog)
                wx = Mock(YES=1, YES_NO=2, ICON_WARNING=4, OK=8, ICON_INFORMATION=16)
                wx.MessageBox.return_value = wx.YES
                handler(reset, wx=wx, DEFAULT_CONFIG=DEFAULT_CONFIG)(dialog, None)
                self.assertFalse(parent.chk_seed.GetValue())
                self.assertEqual(parent.spin_seed.GetValue(), 0)
                self.assertFalse(parent.spin_seed.enabled)
                self.assertFalse(dialog.cfg["use_fixed_seed"])
                self.assertEqual(dialog.cfg["ai_seed"], 0)
                handler("_restore_parent_ai_state")(dialog)
                self.assertTrue(parent.chk_seed.GetValue())
                self.assertEqual(parent.spin_seed.GetValue(), 42)
                self.assertTrue(parent.spin_seed.enabled)

    def test_successful_close_persists_seed_only_when_remembering_is_enabled(self):
        for remember in (False, True):
            with self.subTest(remember=remember):
                frame = Mock(
                    cfg=dict(
                        DEFAULT_CONFIG,
                        warn_exit=False,
                        clean_temp=False,
                        remember_ai_settings=remember,
                    ),
                    current_op=None,
                    rec_stream=None,
                    rec_data=[],
                    _closing=False,
                    _confirming_close=False,
                )
                frame.chk_seed.GetValue.return_value = True
                frame.spin_seed.GetValue.return_value = 42
                save = Mock()
                handler("OnCloseWindow", wx=Mock(), SaveBasicConfig=save, logging=logging)(
                    frame, Mock()
                )
                save.assert_called_once()
                self.assertEqual(save.call_args.args[0]["use_fixed_seed"], remember)
                self.assertEqual(save.call_args.args[0]["ai_seed"], 42 if remember else 0)


if __name__ == "__main__":
    unittest.main()
