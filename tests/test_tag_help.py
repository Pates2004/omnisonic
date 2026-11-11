"""Voice tag help is readable, focusable text rather than a message-box label."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


def load_handler(namespace):
    tree = ast.parse((ROOT / "omnisonic/app.py").read_text(encoding="utf-8"))
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "OnShowTags"
    )
    exec(compile(ast.Module(body=[method], type_ignores=[]), "tag-help", "exec"), namespace)
    return namespace["OnShowTags"]


class TagHelpDispatchTests(unittest.TestCase):
    def test_help_opens_read_only_reader_with_complete_translation(self):
        dialog = Mock()
        factory = Mock(return_value=dialog)
        frame = SimpleNamespace(_=lambda key: "translated:" + key, cfg={"font_size": 16})
        native_message = Mock()
        wx = SimpleNamespace(MessageBox=native_message, OK=1, ICON_INFORMATION=2)
        handler = load_handler({"wx": wx, "ReadOnlyTextDialog": factory})
        handler(frame, None)
        native_message.assert_not_called()
        factory.assert_called_once_with(
            frame,
            "translated:title_tags",
            "translated:msg_tags",
            "translated:btn_close",
            font_size=16,
        )
        dialog.ShowModal.assert_called_once_with()
        dialog.Destroy.assert_called_once_with()

    def test_reader_is_destroyed_if_modal_dispatch_fails(self):
        dialog = Mock()
        dialog.ShowModal.side_effect = RuntimeError("synthetic modal failure")
        factory = Mock(return_value=dialog)
        frame = SimpleNamespace(_=lambda key: key, cfg={})
        handler = load_handler({"ReadOnlyTextDialog": factory})
        with self.assertRaisesRegex(RuntimeError, "synthetic modal failure"):
            handler(frame, None)
        dialog.Destroy.assert_called_once_with()


class FakeDialog:
    def __init__(self, *args, **kwargs):
        self.alive = True
        self.creation = (args, kwargs)
        for name in ("SetEscapeId", "SetFont", "Bind", "CentreOnParent"):
            setattr(self, name, Mock())
        self.GetFont = Mock(return_value="native font")
        self.IsShownOnScreen = Mock(return_value=True)

    def __bool__(self):
        return self.alive

    def ShowModal(self):
        return 5101


class TagHelpControlTests(unittest.TestCase):
    def setUp(self):
        self.text = Mock()
        self.button = Mock()
        self.font = Mock()
        self.wx = SimpleNamespace(
            Dialog=FakeDialog,
            DEFAULT_DIALOG_STYLE=1,
            RESIZE_BORDER=2,
            TE_MULTILINE=4,
            TE_READONLY=8,
            TE_DONTWRAP=16,
            VERTICAL=32,
            ALL=64,
            EXPAND=128,
            ALIGN_RIGHT=256,
            ID_CANCEL=5101,
            EVT_SHOW="show",
            Panel=Mock(),
            TextCtrl=Mock(return_value=self.text),
            Button=Mock(return_value=self.button),
            BoxSizer=Mock(),
            Font=Mock(return_value=self.font),
            CallAfter=Mock(),
            Window=SimpleNamespace(FindFocus=Mock()),
        )
        self.theme = Mock()
        tree = ast.parse((ROOT / "omnisonic/help_dialogs.py").read_text(encoding="utf-8"))
        definitions = [
            node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        ]
        namespace = {
            "wx": self.wx,
            "apply_theme": self.theme,
            "theme_for_window": lambda parent: "dark",
        }
        exec(
            compile(ast.Module(body=definitions, type_ignores=[]), "tag-reader", "exec"), namespace
        )
        self.restore_focus = namespace["_restore_focus"]
        self.parent = object()
        self.dialog = namespace["ReadOnlyTextDialog"](
            self.parent, "Voice tags", "Full tags\n[laughter]\n[sigh]", "Close", font_size=16
        )

    def test_read_only_field_keeps_complete_content_accessible_name_and_fonts(self):
        arguments = self.wx.TextCtrl.call_args.kwargs
        self.assertEqual(arguments["value"], "Full tags\n[laughter]\n[sigh]")
        self.assertTrue(arguments["style"] & self.wx.TE_MULTILINE)
        self.assertTrue(arguments["style"] & self.wx.TE_READONLY)
        self.text.SetName.assert_called_once_with("Voice tags")
        self.text.Disable.assert_not_called()
        self.font.SetPointSize.assert_called_once_with(16)
        self.text.SetFont.assert_called_once_with(self.font)
        self.button.SetFont.assert_called_once_with(self.font)
        self.theme.assert_called_once_with(self.dialog, "dark")

    def test_close_uses_translated_label_and_standard_escape_route(self):
        self.wx.Button.assert_called_once_with(self.wx.Panel.return_value, 5101, "Close")
        self.button.SetName.assert_called_once_with("Close")
        self.dialog.SetEscapeId.assert_called_once_with(5101)
        self.assertTrue(self.dialog.creation[1]["style"] & self.wx.RESIZE_BORDER)

    def test_show_queues_focus_and_starts_at_first_character(self):
        event = SimpleNamespace(IsShown=lambda: True, Skip=Mock())
        self.dialog._on_show(event)
        event.Skip.assert_called_once_with()
        self.wx.CallAfter.assert_called_once_with(self.dialog._focus_text)
        self.dialog._focus_text()
        self.text.SetInsertionPoint.assert_called_once_with(0)
        self.text.ShowPosition.assert_called_once_with(0)
        self.text.SetFocus.assert_called_once_with()

    def test_hidden_or_destroyed_dialog_does_not_refocus_after_close(self):
        event = SimpleNamespace(IsShown=lambda: False, Skip=Mock())
        self.dialog._on_show(event)
        self.wx.CallAfter.assert_not_called()
        self.dialog.IsShownOnScreen.return_value = False
        self.dialog._focus_text()
        self.dialog.alive = False
        self.dialog.IsShownOnScreen.side_effect = RuntimeError("native window destroyed")
        self.dialog._focus_text()
        self.text.SetFocus.assert_not_called()

    def test_modal_return_queues_safe_parent_focus_restoration(self):
        previous_focus = Mock()
        self.wx.Window.FindFocus.return_value = previous_focus
        self.assertEqual(self.dialog.ShowModal(), self.wx.ID_CANCEL)
        self.wx.CallAfter.assert_called_once_with(self.restore_focus, previous_focus)
        self.restore_focus(previous_focus)
        previous_focus.SetFocus.assert_called_once_with()
        previous_focus.SetFocus.reset_mock()
        previous_focus.IsEnabled.return_value = False
        self.restore_focus(previous_focus)
        self.restore_focus(None)
        previous_focus.SetFocus.assert_not_called()


if __name__ == "__main__":
    unittest.main()
