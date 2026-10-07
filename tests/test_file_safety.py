"""I/O regressions using synthetic files, never application or user data."""

import ast
import logging
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import numpy as np

from omnisonic.files import atomic_write, write_numbered_audio
from omnisonic.operations import OperationState
from omnisonic.validation import (
    output_directory_path,
    safe_child_path,
    validate_filename_component,
    validation_error_message,
)

ROOT = Path(__file__).resolve().parents[1]


def app_methods(names, namespace):
    namespace.setdefault("output_directory_path", output_directory_path)
    tree = ast.parse((ROOT / "omnisonic/app.py").read_text(encoding="utf-8"))
    methods = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    for method in methods:
        method.decorator_list = []
    exec(compile(ast.Module(body=methods, type_ignores=[]), "app_methods", "exec"), namespace)
    return namespace


class FileSafetyTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "trash").mkdir(exist_ok=True)
        self.scratch = Path(tempfile.mkdtemp(prefix="file-safety-", dir=ROOT / "trash"))

    def test_failed_write_preserves_existing_file_and_cleans_partial_output(self):
        destination = self.scratch / "voice.wav"
        destination.write_bytes(b"original")

        def fail(temporary):
            temporary.write_bytes(b"partial")
            raise OSError("disk full")

        with self.assertRaisesRegex(OSError, "disk full"):
            atomic_write(destination, fail)
        self.assertEqual(destination.read_bytes(), b"original")
        self.assertEqual(list(self.scratch.iterdir()), [destination])

    def test_cancelled_preset_preserves_original(self):
        destination = self.scratch / "voice.pt"
        destination.write_bytes(b"original")
        state = OperationState()

        def save(path):
            Path(path).write_bytes(b"replacement")
            state.request_cancel()

        save_prompt = app_methods(
            {"_SavePromptAtomically"},
            {"atomic_write": atomic_write, "safe_child_path": safe_child_path, "Path": Path},
        )["_SavePromptAtomically"]
        from omnisonic.operations import OperationCancelled

        with self.assertRaises(OperationCancelled):
            save_prompt(state, SimpleNamespace(save=save), destination)
        self.assertEqual(destination.read_bytes(), b"original")
        self.assertEqual(list(self.scratch.iterdir()), [destination])

    def test_concurrent_saves_use_independent_temporary_files(self):
        barrier = threading.Barrier(2, timeout=10)
        first_committed = threading.Event()
        temporaries = []
        destination = self.scratch / "voice.pt"

        def save(value):
            def writer(path):
                temporaries.append(path)
                path.write_bytes(value)
                barrier.wait()
                if value == b"two":
                    self.assertTrue(first_committed.wait(10))

            # Stage both writes concurrently, then publish in order. Windows may
            # reject simultaneous replacements with a sharing/access violation;
            # this tests staging isolation, not unsupported rename concurrency.
            try:
                atomic_write(destination, writer)
            finally:
                if value == b"one":
                    first_committed.set()

        with ThreadPoolExecutor(2) as pool:
            list(pool.map(save, [b"one", b"two"]))
        self.assertEqual(len(set(temporaries)), 2)
        self.assertEqual(destination.read_bytes(), b"two")
        self.assertEqual(list(self.scratch.iterdir()), [destination])

    def test_numbered_output_does_not_overwrite_other_instances(self):
        first = self.scratch / "voice_1.wav"
        first.write_bytes(b"existing")
        barrier = threading.Barrier(2, timeout=10)

        def save(value):
            def writer(path):
                path.write_bytes(value)
                barrier.wait()

            return write_numbered_audio(self.scratch, "voice", writer)

        with ThreadPoolExecutor(2) as pool:
            paths = list(pool.map(save, [b"one", b"two"]))
        self.assertEqual({p.name for p in paths}, {"voice_2.wav", "voice_3.wav"})
        self.assertEqual([p.read_bytes() for p in paths], [b"one", b"two"])
        self.assertEqual(first.read_bytes(), b"existing")

    def test_failed_numbered_save_removes_its_reservation_only(self):
        first = self.scratch / "voice_1.wav"
        first.write_bytes(b"existing")
        with self.assertRaisesRegex(OSError, "no space"):
            write_numbered_audio(self.scratch, "voice", Mock(side_effect=OSError("no space")))
        self.assertEqual(list(self.scratch.iterdir()), [first])

    def test_config_write_failure_does_not_leave_temporary_config_files(self):
        from omnisonic.config import save_config

        destination = self.scratch / "settings.json"
        destination.write_bytes(b"original")
        factory = tempfile.NamedTemporaryFile

        def failing_file(*args, **kwargs):
            stream = factory(*args, **kwargs)
            stream.write = Mock(side_effect=OSError("disk full"))
            return stream

        with patch("omnisonic.config.tempfile.NamedTemporaryFile", side_effect=failing_file):
            with self.assertRaisesRegex(OSError, "disk full"):
                save_config({}, destination)
        self.assertEqual(destination.read_bytes(), b"original")
        self.assertEqual(list(self.scratch.iterdir()), [destination])

    def test_save_as_opens_even_if_configured_directory_is_unusable(self):
        configured = self.scratch / "not-a-directory"
        configured.write_bytes(b"not a folder")
        destination = self.scratch / "selected.wav"
        wx = MagicMock(ID_CANCEL=1)
        dialog = wx.FileDialog.return_value.__enter__.return_value
        dialog.ShowModal.return_value = 2
        dialog.GetPath.return_value = str(destination)
        sf = Mock()
        sf.write.side_effect = lambda path, data, fs: Path(path).write_bytes(b"audio")
        namespace = app_methods(
            {"PerformSaveAudio"},
            dict(
                Path=Path,
                os=os,
                wx=wx,
                sf=sf,
                atomic_write=atomic_write,
                write_numbered_audio=write_numbered_audio,
                validate_filename_component=validate_filename_component,
                default_audio_directory=lambda kind: self.scratch / kind,
            ),
        )
        frame = SimpleNamespace(cfg={"generated_audio_directory": str(configured)}, _=lambda k: k)
        result = namespace["PerformSaveAudio"](frame, [], 24000, force_dialog=True)
        self.assertEqual(result, str(destination))
        self.assertEqual(destination.read_bytes(), b"audio")
        self.assertEqual(configured.read_bytes(), b"not a folder")
        frame.cfg["generated_audio_directory"] = '"unfinished'
        self.assertEqual(
            namespace["PerformSaveAudio"](frame, [], 24000, force_dialog=True), str(destination)
        )
        dialog.ShowModal.return_value = wx.ID_CANCEL
        frame.cfg["generated_audio_directory"] = str(self.scratch / "do-not-create")
        self.assertIsNone(namespace["PerformSaveAudio"](frame, [], 24000, force_dialog=True))
        self.assertFalse((self.scratch / "do-not-create").exists())

    def test_automatic_recorded_and_generated_audio_accept_quoted_folders(self):
        sf = Mock()
        sf.write.side_effect = lambda path, data, fs: Path(path).write_bytes(b"synthetic audio")
        save = app_methods(
            {"PerformSaveAudio"},
            dict(
                Path=Path,
                sf=sf,
                wx=Mock(),
                write_numbered_audio=write_numbered_audio,
                validate_filename_component=validate_filename_component,
                validation_error_message=validation_error_message,
                default_audio_directory=lambda kind: self.scratch / kind,
            ),
        )["PerformSaveAudio"]
        for generated, kind in ((True, "generated"), (False, "recorded")):
            folder = self.scratch / kind
            frame = SimpleNamespace(
                cfg={
                    "auto_save_gen_folder": True,
                    "auto_save_rec_folder": True,
                    kind + "_audio_directory": f'"{folder}"',
                },
                _=lambda key: key,
            )
            result = Path(save(frame, [], 24000, is_generated=generated))
            self.assertEqual(result.parent, folder)
            self.assertEqual(result.read_bytes(), b"synthetic audio")


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.sd, self.wx = Mock(), MagicMock()
        self.sd.InputStream.return_value.samplerate = 48000
        self.write = Mock()
        self.sf = Mock()
        handlers = {"ToggleRecord", "_CloseRecording", "_UpdateRecordingControls", "_SaveRecording"}
        namespace = app_methods(
            handlers,
            dict(
                sd=self.sd,
                wx=self.wx,
                np=np,
                logging=logging,
                atomic_write=self.write,
                RECORDED_AUDIO_FILE=Path("synthetic.wav"),
                sf=self.sf,
                validation_error_message=validation_error_message,
            ),
        )
        self.frame = SimpleNamespace(
            cfg={},
            current_op=None,
            rec_stream=None,
            rec_data=[],
            rec_fs=48000,
            PerformSaveAudio=Mock(),
            _set_operation_controls_enabled=Mock(),
            _=lambda key: key,
        )
        for name in handlers:
            setattr(self.frame, name, namespace[name].__get__(self.frame))
        self.button, self.path = Mock(), Mock()

    def test_failed_start_closes_stream_and_allows_retry(self):
        broken, working = Mock(samplerate=48000), Mock(samplerate=48000)
        broken.start.side_effect = RuntimeError("device disconnected")
        self.sd.InputStream.side_effect = [broken, working]
        self.frame.ToggleRecord(self.button, self.path)
        broken.close.assert_called_once()
        self.assertIsNone(self.frame.rec_stream)
        self.assertEqual(self.frame.rec_data, [])
        self.frame.ToggleRecord(self.button, self.path)
        self.assertIs(self.frame.rec_stream, working)
        working.start.assert_called_once()

    def test_failed_stop_still_closes_and_releases_microphone(self):
        stream = Mock()
        stream.stop.side_effect = RuntimeError("driver error")
        self.frame.rec_stream = stream
        self.frame.rec_data = [np.ones((10, 1))]
        self.frame.ToggleRecord(self.button, self.path)
        stream.close.assert_called_once()
        self.assertIsNone(self.frame.rec_stream)
        self.assertEqual(len(self.frame.rec_data), 1)
        self.button.SetLabel.assert_called_with("record_retry_save")
        self.write.assert_not_called()
        self.path.SetValue.assert_not_called()

    def test_default_stream_rate_is_preserved_in_recorded_wav(self):
        self.write.side_effect = lambda _path, writer: writer(Path("temporary.wav"))
        for rate in (44100, 48000):
            with self.subTest(rate=rate):
                self.sd.InputStream.return_value.samplerate = rate
                self.frame.ToggleRecord(self.button, self.path)
                self.assertNotIn("samplerate", self.sd.InputStream.call_args.kwargs)
                callback = self.sd.InputStream.call_args.kwargs["callback"]
                callback(np.ones((10, 1)), 10, None, None)
                self.frame.ToggleRecord(self.button, self.path)
                self.assertEqual(self.sf.write.call_args.args[2], rate)
                self.assertEqual(self.frame.rec_data, [])
                self.assertIsNone(self.frame.rec_stream)

    def test_failed_temp_save_keeps_audio_until_successful_save_as(self):
        chunks = [np.ones((10, 1))]
        self.frame.rec_stream = Mock()
        self.frame.rec_data = chunks
        self.write.side_effect = OSError("read-only temporary directory")
        self.frame.ToggleRecord(self.button, self.path)
        self.assertIs(self.frame.rec_data, chunks)
        self.path.SetValue.assert_not_called()
        self.button.SetLabel.assert_called_with("record_retry_save")

        self.frame.PerformSaveAudio.return_value = None
        self.frame.ToggleRecord(self.button, self.path)
        self.assertIs(self.frame.rec_data, chunks)
        self.path.SetValue.assert_not_called()

        self.frame.PerformSaveAudio.side_effect = OSError("destination disconnected")
        self.frame.ToggleRecord(self.button, self.path)
        self.assertIs(self.frame.rec_data, chunks)

        self.frame.PerformSaveAudio.side_effect = None
        self.frame.PerformSaveAudio.return_value = "recovered.wav"
        self.frame.ToggleRecord(self.button, self.path)
        self.assertEqual(self.frame.rec_data, [])
        self.path.SetValue.assert_called_once_with("recovered.wav")
        self.button.SetLabel.assert_called_with("rec_ref")
        self.assertTrue(self.frame.PerformSaveAudio.call_args.kwargs["force_dialog"])
        self.assertFalse(self.frame.PerformSaveAudio.call_args.kwargs["is_generated"])
        self.sd.InputStream.assert_not_called()

    def test_failed_automatic_export_keeps_audio_and_temp_reference(self):
        self.frame.cfg["auto_save_rec"] = True
        self.frame.rec_stream = Mock()
        chunks = [np.ones((10, 1))]
        self.frame.rec_data = chunks
        self.frame.PerformSaveAudio.side_effect = OSError("export failed")
        self.frame.ToggleRecord(self.button, self.path)
        self.write.assert_called_once()
        self.path.SetValue.assert_called_once_with("synthetic.wav")
        self.assertIs(self.frame.rec_data, chunks)
        self.button.SetLabel.assert_called_with("record_retry_save")

    def test_cancelled_optional_export_does_not_discard_saved_reference(self):
        self.frame.cfg["auto_save_rec"] = True
        self.frame.rec_stream = Mock()
        self.frame.rec_data = [np.ones((10, 1))]
        self.frame.PerformSaveAudio.return_value = None
        self.frame.ToggleRecord(self.button, self.path)
        self.assertEqual(self.frame.rec_data, [])
        self.path.SetValue.assert_called_once_with("synthetic.wav")
        self.wx.MessageBox.assert_not_called()

    def test_partial_failed_start_preserves_chunks_for_recovery(self):
        def fail_after_capture():
            callback = self.sd.InputStream.call_args.kwargs["callback"]
            callback(np.ones((10, 1)), 10, None, None)
            raise RuntimeError("device disconnected")

        self.sd.InputStream.return_value.start.side_effect = fail_after_capture
        self.frame.ToggleRecord(self.button, self.path)
        self.assertIsNone(self.frame.rec_stream)
        self.assertEqual(len(self.frame.rec_data), 1)
        self.button.SetLabel.assert_called_with("record_retry_save")

    def test_active_worker_blocks_new_recording_and_pending_save(self):
        self.frame.current_op = OperationState()
        for pending in ([], [np.ones((10, 1))]):
            with self.subTest(pending=bool(pending)):
                self.frame.rec_data = pending
                self.frame.ToggleRecord(self.button, self.path)
                self.assertIs(self.frame.rec_data, pending)
        self.sd.InputStream.assert_not_called()
        self.write.assert_not_called()
        self.frame.PerformSaveAudio.assert_not_called()

    def test_old_callback_cannot_contaminate_new_recording(self):
        self.frame.ToggleRecord(self.button, self.path)
        old_callback = self.sd.InputStream.call_args.kwargs["callback"]
        old_callback(np.ones((10, 1)), 10, None, None)
        self.frame.ToggleRecord(self.button, self.path)
        self.assertEqual(self.frame.rec_data, [])
        self.frame.ToggleRecord(self.button, self.path)
        old_callback(np.ones((10, 1)), 10, None, None)
        self.assertEqual(self.frame.rec_data, [])
        callback = self.sd.InputStream.call_args.kwargs["callback"]
        callback(np.ones((10, 1)), 10, None, None)
        self.assertEqual(len(self.frame.rec_data), 1)

    def test_closing_without_stream_is_safe(self):
        self.frame._CloseRecording()
        self.assertIsNone(self.frame.rec_stream)


class RecordingGatingTests(unittest.TestCase):
    def setUp(self):
        self.wx = MagicMock(ID_YES=1, YES_NO=2, ICON_QUESTION=4, OK=8, ICON_WARNING=16)
        self.wx.GetTopLevelWindows.return_value = []
        self.save_config = Mock()
        self.operation_dialog = Mock()
        handlers = {
            "RunOperation",
            "_set_operation_controls_enabled",
            "AutoLoadModel",
            "OnCloseWindow",
            "_CloseRecording",
        }
        namespace = app_methods(
            handlers,
            dict(
                wx=self.wx,
                os=Mock(),
                logging=logging,
                SaveBasicConfig=self.save_config,
                OperationDialog=self.operation_dialog,
                RECORDED_AUDIO_FILE="unused.wav",
            ),
        )
        self.frame = SimpleNamespace(
            current_op=None,
            rec_stream=None,
            rec_data=[],
            model=None,
            cfg={"warn_exit": False, "remember_ai_settings": False, "clean_temp": False},
            _closing=False,
            _confirming_close=False,
            _autoload_timer=Mock(),
            _reference_timer=Mock(),
            IsBeingDeleted=Mock(return_value=False),
            OnToggleModel=Mock(),
            OnStopAudio=Mock(),
            Destroy=Mock(),
            btn_gen_clone=Mock(),
            btn_rec_ref=Mock(),
            item_generate=Mock(),
            item_record=Mock(),
            item_settings=Mock(),
            Log=Mock(),
            _=lambda key: key,
        )
        for name in handlers:
            setattr(self.frame, name, namespace[name].__get__(self.frame))

    def test_recording_and_pending_audio_block_operations_but_not_stop_or_retry(self):
        for active in (False, True):
            with self.subTest(active=active):
                self.frame.rec_stream = Mock() if active else None
                self.frame.rec_data = [] if active else [np.ones((10, 1))]
                self.frame._set_operation_controls_enabled(True)
                self.frame.btn_gen_clone.Enable.assert_called_with(False)
                self.frame.item_generate.Enable.assert_called_with(False)
                self.frame.item_settings.Enable.assert_called_with(False)
                self.frame.btn_rec_ref.Enable.assert_called_with(True)
                self.frame.item_record.Enable.assert_called_with(True)
                self.assertIsNone(self.frame.RunOperation("title", "message", Mock()))
                self.operation_dialog.assert_not_called()

        self.frame.rec_stream = None
        self.frame.rec_data = []
        self.frame._set_operation_controls_enabled(False)
        self.frame.btn_rec_ref.Enable.assert_called_with(False)
        self.frame.item_record.Enable.assert_called_with(False)
        self.frame._set_operation_controls_enabled(True)
        self.frame.btn_gen_clone.Enable.assert_called_with(True)

    def test_autoload_waits_without_dialog_until_recording_has_been_saved(self):
        self.frame.rec_stream = Mock()
        self.frame.AutoLoadModel()
        self.frame.rec_stream = None
        self.frame.rec_data = [np.ones((10, 1))]
        self.frame.AutoLoadModel()
        self.frame.OnToggleModel.assert_not_called()
        self.wx.MessageBox.assert_not_called()
        self.assertEqual(self.wx.CallLater.call_count, 2)
        self.frame.rec_data = []
        self.frame.AutoLoadModel()
        self.frame.OnToggleModel.assert_called_once_with(None)

    def test_close_warns_before_discarding_active_or_pending_audio_even_without_exit_warning(self):
        for active in (False, True):
            with self.subTest(active=active):
                self.frame._closing = False
                stream = Mock() if active else None
                self.frame.rec_stream = stream
                chunks = [np.ones((10, 1))]
                self.frame.rec_data = chunks
                self.wx.MessageDialog.reset_mock()
                self.wx.MessageDialog.return_value.ShowModal.return_value = 0
                event = Mock()
                self.frame.OnCloseWindow(event)
                event.Veto.assert_called_once()
                self.assertIs(self.frame.rec_data, chunks)
                self.assertIs(self.frame.rec_stream, stream)
                if stream:
                    stream.close.assert_not_called()
                self.frame.Destroy.assert_not_called()
                self.save_config.assert_not_called()
                self.assertEqual(self.wx.MessageDialog.call_args.args[1], "record_discard_close")

    def test_confirmed_close_discards_pending_audio_with_only_one_warning(self):
        self.frame.cfg["warn_exit"] = True
        self.frame.rec_data = [np.ones((10, 1))]
        self.frame.rec_stream = Mock()
        stream = self.frame.rec_stream
        self.wx.MessageDialog.return_value.ShowModal.return_value = self.wx.ID_YES
        self.frame.OnCloseWindow(Mock())
        self.wx.MessageDialog.assert_called_once()
        stream.close.assert_called_once_with(ignore_errors=False)
        self.assertEqual(self.frame.rec_data, [])
        self.assertIsNone(self.frame.rec_stream)
        self.frame.Destroy.assert_called_once()

    def test_failed_settings_save_aborts_close_without_discarding_audio(self):
        self.frame.rec_data = [np.ones((10, 1))]
        chunks = self.frame.rec_data
        self.wx.MessageDialog.return_value.ShowModal.return_value = self.wx.ID_YES
        self.save_config.side_effect = OSError("settings are read-only")
        event = Mock()
        self.frame.OnCloseWindow(event)
        event.Veto.assert_called_once()
        self.assertIs(self.frame.rec_data, chunks)
        self.frame.Destroy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
