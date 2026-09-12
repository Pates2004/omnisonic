"""Exercise real GUI handlers without wx/GPU imports or timing-dependent threads."""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from omnisonic.operations import OperationState


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.wx = Mock(ID_YES=1, YES_NO=2, ICON_QUESTION=4, OK=8, ICON_WARNING=16)
        self.dialog = Mock()
        namespace = {"wx": self.wx, "OperationDialog": self.dialog}
        source = ast.parse(
            (Path(__file__).resolve().parents[1] / "omnisonic/app.py").read_text(encoding="utf-8")
        )
        handlers = {"RunOperation", "EndOperation", "OnStopOperation", "OnCloseWindow"}
        methods = [
            node
            for node in ast.walk(source)
            if isinstance(node, ast.FunctionDef) and node.name in handlers
        ]
        exec(compile(ast.Module(body=methods, type_ignores=[]), "handlers", "exec"), namespace)
        self.state = OperationState()
        self.frame = SimpleNamespace(
            current_op=self.state,
            cfg={"show_progress": True},
            prog_timer=Mock(),
            gauge=Mock(),
            btn_stop=Mock(),
            Log=Mock(),
            _=lambda key: key,
            _set_operation_controls_enabled=Mock(),
            _complete_operation=Mock(),
        )
        for name in handlers:
            setattr(self.frame, name, namespace[name].__get__(self.frame))

    def start(self):
        return self.frame.RunOperation("title", "message", Mock())

    def test_finished_worker_is_busy_until_gui_completion(self):
        self.state.finished_event.set()
        self.assertIsNone(self.start())
        self.dialog.assert_not_called()
        self.assertIs(self.frame.current_op, self.state)
        self.wx.MessageBox.assert_called_once()

    def test_stale_completion_does_not_touch_current_operation(self):
        self.frame.EndOperation(OperationState(), Mock())
        self.frame.prog_timer.Stop.assert_not_called()
        self.frame._complete_operation.assert_not_called()
        self.frame._set_operation_controls_enabled.assert_not_called()

    def test_completion_reserves_model_until_result_callback_finishes(self):
        def complete(state, callback):
            self.assertIs(self.frame.current_op, state)
            self.assertIsNone(self.start())  # E.g. events dispatched by a Save As dialog.
            self.dialog.assert_not_called()

        self.frame._complete_operation.side_effect = complete
        self.frame.EndOperation(self.state, Mock())
        self.assertIsNone(self.frame.current_op)
        self.frame._set_operation_controls_enabled.assert_called_once_with(True)
        self.frame.EndOperation(self.state, Mock())
        self.frame._complete_operation.assert_called_once()

    def test_completion_failure_still_restores_controls(self):
        self.frame._complete_operation.side_effect = ValueError("callback failed")
        with self.assertRaisesRegex(ValueError, "callback failed"):
            self.frame.EndOperation(self.state, None)
        self.assertIsNone(self.frame.current_op)
        self.frame._set_operation_controls_enabled.assert_called_once_with(True)

    def finish_during_confirmation(self):
        self.state.finished_event.set()
        self.frame.EndOperation(self.state, None)
        return self.wx.ID_YES

    def test_stop_confirmation_cannot_cancel_a_completed_or_new_operation(self):
        replacement = OperationState()

        def finish_and_start_new():
            self.finish_during_confirmation()
            self.frame.current_op = replacement
            return self.wx.ID_YES

        for confirm in (self.finish_during_confirmation, finish_and_start_new):
            self.frame.current_op = self.state
            self.state.finished_event.clear()
            self.wx.MessageDialog.return_value.ShowModal.side_effect = confirm
            self.frame.OnStopOperation(None)
            self.assertFalse(self.state.cancel_flag)
            self.assertFalse(replacement.cancel_flag)

    def test_close_waits_for_queued_completion_and_handles_dialog_reentrancy(self):
        self.state.finished_event.set()
        self.wx.MessageDialog.return_value.ShowModal.side_effect = self.finish_during_confirmation
        event = Mock()
        self.frame.OnCloseWindow(event)
        event.Veto.assert_called_once()
        self.assertIsNone(self.frame.current_op)
        self.assertFalse(self.state.cancel_flag)

    def test_modal_branch_uses_same_completion_barrier(self):
        self.frame.current_op = None
        self.dialog.return_value.state = self.state
        self.dialog.return_value.ShowModal.return_value = self.state

        def complete(state, callback):
            self.assertIs(self.frame.current_op, state)
            self.frame._set_operation_controls_enabled.assert_called_once_with(False)

        self.frame._complete_operation.side_effect = complete
        self.assertIs(self.start(), self.state)
        self.assertIsNone(self.frame.current_op)


if __name__ == "__main__":
    unittest.main()
