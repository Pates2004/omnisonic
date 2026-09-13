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
from omnisonic.validation import validate_filename_component

ROOT = Path(__file__).resolve().parents[1]


def app_methods(names, namespace):
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

        save_prompt = app_methods({"_SavePromptAtomically"}, {"atomic_write": atomic_write})[
            "_SavePromptAtomically"
        ]
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
        dialog.ShowModal.return_value = wx.ID_CANCEL
        frame.cfg["generated_audio_directory"] = str(self.scratch / "do-not-create")
        self.assertIsNone(namespace["PerformSaveAudio"](frame, [], 24000, force_dialog=True))
        self.assertFalse((self.scratch / "do-not-create").exists())


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.sd, self.wx = Mock(), MagicMock()
        self.write = Mock()
        namespace = app_methods(
            {"ToggleRecord", "_CloseRecording"},
            dict(
                sd=self.sd,
                wx=self.wx,
                np=np,
                logging=logging,
                atomic_write=self.write,
                RECORDED_AUDIO_FILE=Path("synthetic.wav"),
                sf=Mock(),
            ),
        )
        self.frame = SimpleNamespace(cfg={}, rec_stream=None, rec_data=[], _=lambda k: k)
        for name in ("ToggleRecord", "_CloseRecording"):
            setattr(self.frame, name, namespace[name].__get__(self.frame))
        self.button, self.path = Mock(), Mock()

    def test_failed_start_closes_stream_and_allows_retry(self):
        broken, working = Mock(), Mock()
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
        self.assertEqual(self.frame.rec_data, [])
        self.write.assert_not_called()
        self.path.SetValue.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
