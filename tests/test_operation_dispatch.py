"""Exercise real GUI handlers without wx/GPU imports or timing-dependent threads."""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call

from omnisonic.operations import OperationState


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.wx = Mock(ID_YES=1, YES_NO=2, ICON_QUESTION=4, OK=8, ICON_WARNING=16)
        self.dialog = Mock()
        self.threading = Mock()
        namespace = {
            "wx": self.wx,
            "OperationDialog": self.dialog,
            "OperationState": OperationState,
            "threading": self.threading,
            "logging": Mock(),
        }
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

    def test_failed_worker_start_completes_error_and_unblocks_retry(self):
        self.frame.current_op = None
        self.frame.cfg["show_progress"] = False
        failure = RuntimeError("can't start new thread")
        self.threading.Thread.return_value.start.side_effect = failure
        state = self.start()
        self.assertTrue(state.finished)
        self.assertIs(state.error, failure)
        self.assertIsNone(self.frame.current_op)
        self.frame.prog_timer.Stop.assert_called_once_with()
        self.frame.btn_stop.Disable.assert_called_once_with()
        self.frame._complete_operation.assert_called_once_with(state, None)
        self.assertEqual(
            self.frame._set_operation_controls_enabled.call_args_list,
            [call(False), call(True)],
        )
        self.threading.Thread.return_value.start.side_effect = None
        replacement = self.start()
        self.assertIs(self.frame.current_op, replacement)
        self.assertFalse(replacement.finished)


class WorkerStartFailureTests(unittest.TestCase):
    def setUp(self):
        self.wx = MagicMock()
        self.threading = Mock()
        self.failure = RuntimeError("can't start new thread")
        self.threading.Thread.return_value.start.side_effect = self.failure
        self.namespace = {
            "wx": self.wx,
            "threading": self.threading,
            "logging": Mock(),
            "apply_theme": Mock(),
        }
        self.tree = ast.parse(
            (Path(__file__).resolve().parents[1] / "omnisonic/app.py").read_text(encoding="utf-8")
        )

    def bind(self, holder, class_name, names):
        node = next(
            item
            for item in self.tree.body
            if isinstance(item, ast.ClassDef) and item.name == class_name
        )
        methods = [
            item for item in node.body if isinstance(item, ast.FunctionDef) and item.name in names
        ]
        namespace = dict(self.namespace)
        exec(compile(ast.Module(body=methods, type_ignores=[]), "worker-start", "exec"), namespace)
        for method in methods:
            setattr(holder, method.name, namespace[method.name].__get__(holder))

    def test_operation_start_failure_finishes_and_destroys_both_progress_modes(self):
        for native in (False, True):
            with self.subTest(native=native):
                self.wx.reset_mock()
                holder = SimpleNamespace(
                    cfg={"use_native_dialogs": native},
                    state=OperationState(),
                    parent=None,
                    title="Synthetic operation",
                    msg="Synthetic message",
                    _run_worker=Mock(),
                    _confirm_cancel=Mock(),
                    _=lambda key: key,
                )
                self.bind(holder, "OperationDialog", {"ShowModal", "_start_worker"})
                state = holder.ShowModal()
                self.assertIs(state, holder.state)
                self.assertTrue(state.finished)
                self.assertIs(state.error, self.failure)
                holder._run_worker.assert_not_called()
                holder.dialog.ShowModal.assert_not_called()
                holder.dialog.Destroy.assert_called_once_with()
                if not native:
                    self.wx.Timer.return_value.Stop.assert_called_once_with()

    def test_import_start_failure_finishes_and_destroys_both_splash_modes(self):
        for native in (False, True):
            with self.subTest(native=native):
                self.wx.reset_mock()
                holder = SimpleNamespace(
                    cfg={"use_native_dialogs": native},
                    parent=None,
                    finished=False,
                    cancel_requested=False,
                    error=None,
                    DoHeavyImports=Mock(),
                    _confirm_cancel=Mock(),
                    _=lambda key: key,
                )
                self.bind(holder, "StartupSplash", {"ShowModal", "_start_imports"})
                self.assertEqual(holder.ShowModal(), self.wx.ID_CANCEL)
                self.assertTrue(holder.finished)
                self.assertIs(holder.error, self.failure)
                holder.DoHeavyImports.assert_not_called()
                holder.dialog.ShowModal.assert_not_called()
                holder.dialog.Destroy.assert_called_once_with()
                if not native:
                    self.wx.Timer.return_value.Stop.assert_called_once_with()

    def test_download_start_failure_closes_as_error_instead_of_waiting_forever(self):
        holder = SimpleNamespace(
            state=OperationState(),
            _run_download=Mock(),
            timer=Mock(),
            _confirming_cancel=False,
            IsModal=Mock(return_value=True),
            EndModal=Mock(),
        )
        self.bind(holder, "DownloadDialog", {"_start_download", "_finish_modal"})
        holder._start_download()
        self.assertTrue(holder.state.finished)
        self.assertIs(holder.state.error, self.failure)
        holder._run_download.assert_not_called()
        holder._finish_modal()
        holder.timer.Stop.assert_called_once_with()
        holder.EndModal.assert_called_once_with(self.wx.ID_CANCEL)

    def test_thread_constructor_failure_is_also_captured(self):
        self.threading.Thread.side_effect = self.failure
        for class_name, method, target in (
            ("OperationDialog", "_start_worker", "_run_worker"),
            ("DownloadDialog", "_start_download", "_run_download"),
        ):
            with self.subTest(class_name=class_name):
                holder = SimpleNamespace(state=OperationState(), **{target: Mock()})
                self.bind(holder, class_name, {method})
                getattr(holder, method)()
                self.assertTrue(holder.state.finished)
                self.assertIs(holder.state.error, self.failure)
                getattr(holder, target).assert_not_called()

    def test_successful_worker_start_does_not_mark_operation_finished(self):
        self.threading.Thread.return_value.start.side_effect = None
        for class_name, method, target in (
            ("OperationDialog", "_start_worker", "_run_worker"),
            ("DownloadDialog", "_start_download", "_run_download"),
        ):
            with self.subTest(class_name=class_name):
                holder = SimpleNamespace(state=OperationState(), **{target: Mock()})
                self.bind(holder, class_name, {method})
                getattr(holder, method)()
                self.assertFalse(holder.state.finished)
                self.assertIsNone(holder.state.error)
                self.threading.Thread.assert_called_with(
                    target=getattr(holder, target), daemon=True
                )
                getattr(holder, target).assert_not_called()

    def test_started_worker_error_still_waits_for_modal_completion(self):
        for class_name, starter in (
            ("OperationDialog", "_start_worker"),
            ("StartupSplash", "_start_imports"),
        ):
            with self.subTest(class_name=class_name):
                self.wx.reset_mock()
                holder = SimpleNamespace(
                    cfg={},
                    parent=None,
                    title="Synthetic operation",
                    msg="Synthetic message",
                    state=OperationState(),
                    error=None,
                    finished=False,
                    cancel_requested=False,
                    _confirm_cancel=Mock(),
                    _=lambda key: key,
                )

                def record_error_before_worker_finishes(holder=holder, starter=starter):
                    if starter == "_start_worker":
                        holder.state.error = self.failure
                    else:
                        holder.error = self.failure
                    return True

                def complete_during_modal(holder=holder, starter=starter):
                    if starter == "_start_worker":
                        self.assertFalse(holder.state.finished)
                        holder.state.finished_event.set()
                    else:
                        self.assertFalse(holder.finished)
                        holder.finished = True
                    return self.wx.ID_CANCEL

                def destroy_after_completion(holder=holder, starter=starter):
                    self.assertTrue(
                        holder.state.finished if starter == "_start_worker" else holder.finished
                    )

                self.wx.Dialog.return_value.ShowModal.side_effect = complete_during_modal
                self.wx.Dialog.return_value.Destroy.side_effect = destroy_after_completion
                setattr(holder, starter, record_error_before_worker_finishes)
                self.bind(holder, class_name, {"ShowModal"})
                holder.ShowModal()
                holder.dialog.ShowModal.assert_called_once_with()
                holder.dialog.Destroy.assert_called_once_with()


class CompletionFocusTests(unittest.TestCase):
    def setUp(self):
        import numpy as np

        source = ast.parse(
            (Path(__file__).resolve().parents[1] / "omnisonic/app.py").read_text(encoding="utf-8")
        )
        self.handlers = {"OnToggleModel", "OnTranscribeReference", "_finish_generation"}
        methods = [
            node
            for node in ast.walk(source)
            if isinstance(node, ast.FunctionDef) and node.name in self.handlers
        ]
        self.namespace = {"wx": Mock(), "np": np, "os": Mock()}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "focus", "exec"), self.namespace)

    def frame(self, shown, enabled):
        frame = Mock(current_op=None, model=None, cfg={"auto_save_gen": False})
        frame._.side_effect = lambda key: key
        frame.clone_ref_audio.GetValue.return_value = "reference.wav"
        frame.clone_ref_text.GetValue.return_value = ""
        for control in (frame.clone_text, frame.clone_ref_text, frame.btn_play):
            control.IsShownOnScreen.return_value = shown
            control.IsEnabled.return_value = enabled
        for name in self.handlers:
            setattr(frame, name, self.namespace[name].__get__(frame))
        return frame

    def test_background_completion_never_focuses_a_hidden_or_disabled_control(self):
        for shown, enabled in ((False, True), (True, False), (True, True)):
            for action in ("model", "transcribe", "generate"):
                with self.subTest(shown=shown, enabled=enabled, action=action):
                    frame = self.frame(shown, enabled)
                    if action == "model":
                        frame.OnToggleModel(None)
                        frame.RunOperation.call_args.kwargs["success_callback"](None)
                        target = frame.clone_text
                    elif action == "transcribe":
                        frame.OnTranscribeReference(None)
                        frame.RunModelOperation.call_args.kwargs["success_callback"]("Transcript")
                        target = frame.clone_ref_text
                    else:
                        frame._finish_generation([0.1, 0.2])
                        target = frame.btn_play
                    if shown and enabled:
                        target.SetFocus.assert_called_once_with()
                    else:
                        target.SetFocus.assert_not_called()


class FrameLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.wx = Mock(ID_YES=1, YES_NO=2, ICON_QUESTION=4)
        self.wx.GetTopLevelWindows.return_value = []
        self.save = Mock()
        namespace = {
            "wx": self.wx,
            "SaveBasicConfig": self.save,
            "RECORDED_AUDIO_FILE": "unused.wav",
            "os": Mock(),
        }
        source = ast.parse(
            (Path(__file__).resolve().parents[1] / "omnisonic/app.py").read_text(encoding="utf-8")
        )
        handlers = {"AutoLoadModel", "OnCloseWindow"}
        methods = [
            node
            for node in ast.walk(source)
            if isinstance(node, ast.FunctionDef) and node.name in handlers
        ]
        exec(compile(ast.Module(body=methods, type_ignores=[]), "lifecycle", "exec"), namespace)
        self.frame = SimpleNamespace(
            current_op=None,
            model=None,
            cfg={"warn_exit": False, "remember_ai_settings": False, "clean_temp": False},
            _closing=False,
            _confirming_close=False,
            _autoload_timer=Mock(),
            _reference_timer=Mock(),
            IsBeingDeleted=Mock(return_value=False),
            OnToggleModel=Mock(),
            _CloseRecording=Mock(),
            OnStopAudio=Mock(),
            Destroy=Mock(),
            Log=Mock(),
            _=lambda key: key,
        )
        for name in handlers:
            setattr(self.frame, name, namespace[name].__get__(self.frame))

    def test_idle_close_does_not_destroy_worker_started_during_confirmation(self):
        self.frame.cfg["warn_exit"] = True

        def start_worker():
            self.frame.current_op = OperationState()
            return self.wx.ID_YES

        self.wx.MessageDialog.return_value.ShowModal.side_effect = start_worker
        event = Mock()
        self.frame.OnCloseWindow(event)
        event.Veto.assert_called_once()
        self.frame.Destroy.assert_not_called()
        self.save.assert_not_called()

    def test_successful_close_stops_pending_autoload(self):
        timer = self.frame._autoload_timer
        self.frame.OnCloseWindow(Mock())
        timer.Stop.assert_called_once()
        self.frame.Destroy.assert_called_once()
        self.frame.AutoLoadModel()
        self.frame.OnToggleModel.assert_not_called()

    def test_autoload_does_not_access_deleted_window(self):
        self.frame.IsBeingDeleted.return_value = True
        self.frame.AutoLoadModel()
        self.frame.OnToggleModel.assert_not_called()
        self.wx.CallLater.assert_not_called()

    def test_autoload_waits_for_modal_dialog_and_continues_after_cancelled_close(self):
        self.frame.cfg["warn_exit"] = True

        def cancel_close():
            self.frame.AutoLoadModel()
            self.frame.OnToggleModel.assert_not_called()
            return 0

        self.wx.MessageDialog.return_value.ShowModal.side_effect = cancel_close
        event = Mock()
        self.frame.OnCloseWindow(event)
        event.Veto.assert_called_once()
        self.assertFalse(self.frame._confirming_close)
        self.frame.AutoLoadModel()
        self.frame.OnToggleModel.assert_called_once_with(None)

    def test_autoload_defers_for_other_modal_windows(self):
        self.wx.GetTopLevelWindows.return_value = [Mock(IsModal=Mock(return_value=True))]
        self.frame.AutoLoadModel()
        self.frame.OnToggleModel.assert_not_called()
        self.wx.CallLater.assert_called_once()

    def test_autoload_waits_for_nonmodal_operation_and_gui_completion(self):
        for finished in (False, True):
            with self.subTest(finished=finished):
                self.setUp()
                state = OperationState()
                if finished:
                    state.finished_event.set()
                self.frame.current_op = state
                self.frame.AutoLoadModel()
                self.frame.OnToggleModel.assert_not_called()
                self.wx.CallLater.assert_called_once()
                self.frame.current_op = None
                self.frame.AutoLoadModel()
                self.frame.OnToggleModel.assert_called_once_with(None)


class ProgressDialogTests(unittest.TestCase):
    def setUp(self):
        self.wx = Mock(ID_YES=1, ID_OK=2, ID_CANCEL=3, YES_NO=4, ICON_QUESTION=8)
        self.wx.CloseEvent = type("CloseEvent", (), {})
        namespace = {"wx": self.wx}
        tree = ast.parse(
            (Path(__file__).resolve().parents[1] / "omnisonic/app.py").read_text(encoding="utf-8")
        )
        dialog_class = next(
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OperationDialog"
        )
        names = {"_request_cancel", "_confirm_cancel", "_finish_custom_dialog"}
        methods = [
            n for n in dialog_class.body if isinstance(n, ast.FunctionDef) and n.name in names
        ]
        exec(compile(ast.Module(body=methods, type_ignores=[]), "progress", "exec"), namespace)
        self.holder = SimpleNamespace(
            state=OperationState(),
            cfg={},
            dialog=Mock(),
            _confirming_cancel=False,
            _=lambda k: k,
        )
        for name in names:
            setattr(self.holder, name, namespace[name].__get__(self.holder))

    def test_finished_result_is_not_cancelled_after_user_confirmation(self):
        for native in (False, True):
            self.setUp()
            self.holder.cfg["use_native_dialogs"] = native

            def finish_while_asking():
                self.holder.state.finished_event.set()
                self.holder._finish_custom_dialog()
                self.holder.dialog.EndModal.assert_not_called()
                return self.wx.ID_YES

            self.wx.MessageDialog.return_value.ShowModal.side_effect = finish_while_asking
            self.holder._confirm_cancel()
            self.assertFalse(self.holder.state.cancel_flag)
            self.assertFalse(self.holder._confirming_cancel)
            if native:
                self.holder.dialog.EndModal.assert_not_called()
            else:
                self.holder.dialog.EndModal.assert_called_once_with(self.wx.ID_OK)

    def test_running_operation_can_still_be_cancelled(self):
        self.wx.MessageDialog.return_value.ShowModal.return_value = self.wx.ID_YES
        self.holder._confirm_cancel()
        self.assertTrue(self.holder.state.cancel_flag)
        self.holder.dialog.EndModal.assert_not_called()

    def test_duplicate_confirmation_and_completed_cancellation_are_ignored(self):
        self.holder._confirming_cancel = True
        self.holder._confirm_cancel()
        self.wx.MessageDialog.assert_not_called()
        self.holder._confirming_cancel = False
        self.holder.state.finished_event.set()
        self.holder._request_cancel()
        self.assertFalse(self.holder.state.cancel_flag)


class StartupAndDownloadDialogTests(unittest.TestCase):
    def setUp(self):
        self.wx = Mock(ID_YES=1, YES=1, ID_OK=2, ID_CANCEL=3, YES_NO=4, ICON_QUESTION=8)
        self.wx.CloseEvent = type("CloseEvent", (), {})
        self.wx.GetApp.return_value = None
        self.wx.CallAfter.side_effect = lambda callback, *args: callback(*args)

    def bind_handlers(self, holder, class_name, names):
        tree = ast.parse(
            (Path(__file__).resolve().parents[1] / "omnisonic/app.py").read_text(encoding="utf-8")
        )
        dialog_class = next(
            node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        methods = [
            node
            for node in dialog_class.body
            if isinstance(node, ast.FunctionDef) and node.name in names
        ]
        namespace = {"wx": self.wx, "logging": Mock(), "LoadRuntimeDependencies": Mock()}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "dialogs", "exec"), namespace)
        for method in methods:
            setattr(holder, method.name, namespace[method.name].__get__(holder))

    def test_startup_completion_waits_for_confirmation_and_honours_answer(self):
        for answer in (self.wx.ID_YES, self.wx.ID_CANCEL):
            with self.subTest(answer=answer):
                holder = SimpleNamespace(
                    cfg={},
                    dialog=Mock(),
                    finished=False,
                    cancel_requested=False,
                    error=None,
                    _confirming_cancel=False,
                    _=lambda key: key,
                )
                self.bind_handlers(
                    holder,
                    "StartupSplash",
                    {"_confirm_cancel", "_finish_custom_dialog", "DoHeavyImports"},
                )

                def finish_while_asking(holder=holder, answer=answer):
                    holder.DoHeavyImports()
                    holder.dialog.EndModal.assert_not_called()
                    return answer

                self.wx.MessageDialog.return_value.ShowModal.side_effect = finish_while_asking
                holder._confirm_cancel()
                self.assertEqual(holder.cancel_requested, answer == self.wx.ID_YES)
                expected = self.wx.ID_CANCEL if holder.cancel_requested else self.wx.ID_OK
                holder.dialog.EndModal.assert_called_once_with(expected)
                self.assertFalse(holder._confirming_cancel)

    def test_download_completion_waits_for_confirmation_without_losing_success(self):
        holder = SimpleNamespace(
            state=OperationState(),
            timer=Mock(),
            gauge=Mock(),
            btn_cancel=Mock(),
            lbl=Mock(),
            EndModal=Mock(),
            IsModal=Mock(return_value=True),
            _confirming_cancel=False,
            _=lambda key: key,
        )
        self.bind_handlers(holder, "DownloadDialog", {"OnCancel", "OnTimer", "_finish_modal"})

        def finish_while_asking(*args, **kwargs):
            holder.state.finished_event.set()
            holder.OnTimer(None)
            holder.EndModal.assert_not_called()
            return self.wx.YES

        self.wx.MessageBox.side_effect = finish_while_asking
        holder.OnCancel(None)
        self.assertFalse(holder.state.cancel_flag)
        self.assertFalse(holder._confirming_cancel)
        holder.EndModal.assert_called_once_with(self.wx.ID_OK)

    def test_running_download_can_still_be_cancelled(self):
        holder = SimpleNamespace(
            state=OperationState(),
            timer=Mock(),
            btn_cancel=Mock(),
            lbl=Mock(),
            EndModal=Mock(),
            IsModal=Mock(return_value=True),
            _confirming_cancel=False,
            _=lambda key: key,
        )
        self.bind_handlers(holder, "DownloadDialog", {"OnCancel", "_finish_modal"})
        self.wx.MessageBox.return_value = self.wx.YES
        holder.OnCancel(None)
        self.assertTrue(holder.state.cancel_flag)
        holder.btn_cancel.Disable.assert_called_once_with()
        holder.EndModal.assert_not_called()
        self.assertIs(self.wx.MessageBox.call_args.kwargs["parent"], holder)


if __name__ == "__main__":
    unittest.main()
