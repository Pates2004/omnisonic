"""Exercise actual advanced numeric handlers without requiring wxPython."""

import ast
import unittest
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from omnisonic.config import DEFAULT_CONFIG, normalize_config


class TextControl:
    def __init__(self, parent, value, style):
        self.text = value

    def GetValue(self):
        return self.text

    def SetValue(self, value):
        self.text = value

    def Bind(self, *args):
        pass

    def SetName(self, name):
        pass

    def SetToolTip(self, text):
        pass


def load_numeric_handlers():
    tree = ast.parse(
        (Path(__file__).resolve().parents[1] / "omnisonic/app.py").read_text(encoding="utf-8")
    )
    names = {"AccessibleFloatCtrl", "GetGenConfig", "SetupAdvTab"}
    nodes = [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names
    ]
    wx = MagicMock()
    wx.TextCtrl = TextControl
    namespace = dict(
        wx=wx,
        Decimal=Decimal,
        InvalidOperation=InvalidOperation,
        OmniVoiceGenerationConfig=SimpleNamespace,
    )
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "numeric-controls", "exec"), namespace)
    return namespace


class NumericControlTests(unittest.TestCase):
    def setUp(self):
        self.handlers = load_numeric_handlers()
        self.control = self.handlers["AccessibleFloatCtrl"](
            None, value=0.001, min_val=0.001, max_val=10.0, inc=0.01
        )

    def test_arrow_step_keeps_fractional_precision_and_visible_minimum(self):
        self.control.Increment(-0.01)
        self.assertEqual(float(self.control.text), 0.001)
        self.control.Increment(0.01)
        self.assertEqual(float(self.control.text), 0.011)
        self.control.Increment(-0.01)
        self.assertEqual(float(self.control.text), 0.001)

    def test_increment_does_not_accumulate_float_error(self):
        for _ in range(100):
            self.control.Increment(0.01)
        self.assertEqual(self.control.GetValue(), 1.001)
        self.assertEqual(float(self.control.text), 1.001)

    def test_nonfinite_text_is_safe_and_arrows_repair_it(self):
        for text in ("NaN", "Infinity", "-Infinity", "bad", ""):
            with self.subTest(text=text):
                self.control.SetValue(text)
                self.assertEqual(self.control.GetValue(), 0.001)
                self.control.Increment(0.01)
                self.assertEqual(float(self.control.text), 0.011)

    def test_zero_guidance_survives_config_controls_and_generation(self):
        settings = normalize_config(dict(DEFAULT_CONFIG, ai_cfg=0.0))
        self.assertEqual(settings["ai_cfg"], 0.0)
        view = SimpleNamespace(cfg=settings, _=lambda key: key)
        self.handlers["SetupAdvTab"](view, MagicMock())
        self.assertEqual(view.spin_cfg.GetValue(), 0.0)
        result = self.handlers["GetGenConfig"](view)
        self.assertEqual(result.guidance_scale, 0.0)


if __name__ == "__main__":
    unittest.main()
