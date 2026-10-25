"""Regression tests for observable startup and hidden-mode diagnostics."""

from __future__ import annotations

import ast
import importlib.metadata
import io
import json
import logging
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from omnisonic.startup import announce_window, run, startup_phase
from omnisonic.operations import OperationState, execute_worker
from tests.materials import scratch_directory


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.folder = scratch_directory("startup-test-")

    def test_readiness_is_published_atomically_with_own_pid(self):
        marker = self.folder / "ready.txt"
        with patch.dict(os.environ, {"OMNISONIC_STARTUP_READY": str(marker)}):
            announce_window()
        self.assertEqual(marker.read_text(encoding="ascii"), str(os.getpid()))
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_hidden_startup_records_failure_and_restores_standard_streams(self):
        log_file = self.folder / "startup.log"
        old_stdout, old_stderr = sys.stdout, sys.stderr

        def fail():
            raise RuntimeError("Simulated early import failure")

        with patch.dict(os.environ, {"OMNISONIC_STARTUP_LOG": str(log_file)}):
            self.assertEqual(run(fail), 1)
        self.assertIn("Simulated early import failure", log_file.read_text(encoding="utf-8"))
        self.assertIs(sys.stdout, old_stdout)
        self.assertIs(sys.stderr, old_stderr)

    def test_process_marker_failure_is_logged_before_application_starts(self):
        log_file = self.folder / "marker-error.log"
        marker = self.folder / "process.txt"
        application = Mock()
        with (
            patch.dict(
                os.environ,
                {"OMNISONIC_STARTUP_LOG": str(log_file), "OMNISONIC_STARTUP_PROCESS": str(marker)},
            ),
            patch(
                "omnisonic.startup.os.replace", side_effect=PermissionError("Process marker locked")
            ),
        ):
            self.assertEqual(run(application), 1)
        application.assert_not_called()
        self.assertIn("Process marker locked", log_file.read_text(encoding="utf-8"))
        self.assertEqual(list(self.folder.glob("*.tmp")), [])

    def test_marker_cleanup_error_does_not_replace_original_failure(self):
        marker = self.folder / "ready.txt"
        with (
            patch.dict(os.environ, {"OMNISONIC_STARTUP_READY": str(marker)}),
            patch(
                "omnisonic.startup.os.replace",
                side_effect=PermissionError("Original marker failure"),
            ),
            patch("pathlib.Path.unlink", side_effect=PermissionError("Secondary cleanup failure")),
            self.assertLogs("omnisonic.startup", level="WARNING") as messages,
        ):
            with self.assertRaisesRegex(PermissionError, "Original marker failure"):
                announce_window()
        self.assertIn("Secondary cleanup failure", "\n".join(messages.output))
        self.assertIn(str(marker) + ".", "\n".join(messages.output))

    def test_success_records_runtime_and_readiness(self):
        log_file = self.folder / "startup.log"
        marker = self.folder / "ready.txt"
        process_marker = self.folder / "process.txt"
        with patch.dict(
            os.environ,
            {
                "OMNISONIC_STARTUP_LOG": str(log_file),
                "OMNISONIC_STARTUP_READY": str(marker),
                "OMNISONIC_STARTUP_PROCESS": str(process_marker),
                "OMNISONIC_ACTIVE_BACKEND": "xpu",
            },
        ):
            self.assertEqual(run(lambda: announce_window() or 0), 0)
        self.assertEqual(marker.read_text(encoding="ascii"), str(os.getpid()))
        self.assertEqual(process_marker.read_text(encoding="ascii"), str(os.getpid()))
        self.assertIn("backend=xpu", log_file.read_text(encoding="utf-8"))

    def test_hidden_log_keeps_traceback_for_a_later_model_worker_failure(self):
        log_file = self.folder / "model-error.log"
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        original_level = root_logger.level

        def missing_model_file(state):
            raise FileNotFoundError(2, "No such file or directory")

        def application():
            logging.basicConfig(level=logging.INFO)
            state = execute_worker(OperationState("model loading"), missing_model_file)
            self.assertIsInstance(state.error, FileNotFoundError)
            return 0

        try:
            root_logger.handlers = []
            with patch.dict(os.environ, {"OMNISONIC_STARTUP_LOG": str(log_file)}):
                self.assertEqual(run(application), 0)
        finally:
            for handler in root_logger.handlers:
                handler.close()
            root_logger.handlers = original_handlers
            root_logger.setLevel(original_level)
        contents = log_file.read_text(encoding="utf-8")
        self.assertIn("model loading failed", contents)
        self.assertIn("Traceback (most recent call last)", contents)
        self.assertIn("missing_model_file", contents)
        self.assertIn("FileNotFoundError: [Errno 2] No such file or directory", contents)

    def test_phase_flushes_directly_to_log_and_rejects_non_identifier_content(self):
        log_file = self.folder / "phases.log"
        stdout = io.StringIO()
        with (
            patch.dict(os.environ, {"OMNISONIC_STARTUP_LOG": str(log_file)}),
            redirect_stdout(stdout),
        ):
            startup_phase("runtime.torch.begin")
            self.assertIn("phase=runtime.torch.begin", log_file.read_text(encoding="utf-8"))
            startup_phase("private reference text\nshould never be a phase")
            startup_phase("C:/private/audio.wav")
        self.assertEqual(stdout.getvalue(), "")
        contents = log_file.read_text(encoding="utf-8")
        self.assertEqual(len(contents.splitlines()), 1)
        self.assertNotIn("private", contents)

    def test_phase_write_failure_cannot_fail_the_application(self):
        log_file = self.folder / "phase-error.log"

        def application():
            with patch("pathlib.Path.open", side_effect=PermissionError("Synthetic log failure")):
                startup_phase("runtime.torch.begin")
            return 0

        with patch.dict(os.environ, {"OMNISONIC_STARTUP_LOG": str(log_file)}):
            self.assertEqual(run(application), 0)
        self.assertIn("finished with status 0", log_file.read_text(encoding="utf-8"))

    def test_no_log_environment_keeps_stdout_unchanged(self):
        stdout = io.StringIO()
        with (
            patch.dict(os.environ, {"OMNISONIC_STARTUP_LOG": ""}),
            redirect_stdout(stdout),
            patch("omnisonic.startup._publish_process"),
        ):
            startup_phase("application.begin")
            self.assertEqual(run(lambda: print("Owned application output")), 0)
        self.assertEqual(stdout.getvalue(), "Owned application output\n")

    def test_runtime_metadata_uses_only_a_fixed_distribution_whitelist(self):
        log_file = self.folder / "metadata.log"
        expected = {
            "omnisonic",
            "wxPython",
            "numpy",
            "torch",
            "torchaudio",
            "transformers",
            "sounddevice",
            "soundfile",
        }
        with (
            patch.dict(os.environ, {"OMNISONIC_STARTUP_LOG": str(log_file)}),
            patch.object(importlib.metadata, "version", return_value="1.2.3") as version,
        ):
            self.assertEqual(run(lambda: 0), 0)
        self.assertEqual({call.args[0] for call in version.call_args_list}, expected)
        self.assertEqual(version.call_count, len(expected))
        lines = log_file.read_text(encoding="utf-8").splitlines()
        line = next(line for line in lines if line.startswith("Runtime metadata: "))
        metadata = json.loads(line.removeprefix("Runtime metadata: "))
        self.assertEqual(metadata["executable"], sys.executable)
        self.assertEqual(metadata["prefix"], sys.prefix)
        self.assertEqual(metadata["base_prefix"], sys.base_prefix)
        self.assertEqual(set(metadata["packages"]), expected)

    def test_unreadable_distribution_metadata_does_not_prevent_startup(self):
        log_file = self.folder / "bad-metadata.log"
        application = Mock(return_value=0)
        with (
            patch.dict(os.environ, {"OMNISONIC_STARTUP_LOG": str(log_file)}),
            patch.object(importlib.metadata, "version", side_effect=OSError("Metadata unreadable")),
        ):
            self.assertEqual(run(application), 0)
        application.assert_called_once_with()
        self.assertIn('"torch": "unavailable"', log_file.read_text(encoding="utf-8"))

    def test_import_failure_records_phase_before_import_and_preserves_traceback(self):
        log_file = self.folder / "import-error.log"
        original_import = __import__

        def fail_application_import(name, *args, **kwargs):
            if name == "app" and kwargs.get("level", args[3] if len(args) > 3 else 0) == 1:
                raise RuntimeError("Synthetic native-module import boundary")
            return original_import(name, *args, **kwargs)

        with (
            patch.dict(os.environ, {"OMNISONIC_STARTUP_LOG": str(log_file)}),
            patch("builtins.__import__", side_effect=fail_application_import),
        ):
            self.assertEqual(run(), 1)
        contents = log_file.read_text(encoding="utf-8")
        self.assertIn("phase=application.import.begin", contents)
        self.assertIn("phase=application.failed", contents)
        self.assertNotIn("phase=application.import.ready", contents)
        self.assertIn("Synthetic native-module import boundary", contents)

    def test_settings_readiness_kind_keeps_the_exact_pid_handshake(self):
        marker = self.folder / "settings-ready.txt"
        log_file = self.folder / "settings-ready.log"
        with patch.dict(
            os.environ,
            {"OMNISONIC_STARTUP_READY": str(marker), "OMNISONIC_STARTUP_LOG": str(log_file)},
        ):
            announce_window(kind="settings")
            self.assertEqual(marker.read_text(encoding="ascii"), str(os.getpid()))
            announce_window()
        contents = log_file.read_text(encoding="utf-8")
        self.assertIn("phase=window.settings.ready", contents)
        self.assertIn("phase=window.main.ready", contents)

    def test_first_settings_window_does_not_claim_main_frame_or_runtime_readiness(self):
        events = []
        callbacks = []
        cfg = {"first_run_done": False, "hide_console": False}

        class Settings:
            def __init__(self, *_args, **_kwargs):
                self.cfg = cfg

            def ShowModal(self):
                for callback in callbacks:
                    callback()
                return 1

            def Destroy(self):
                pass

        def fail_runtime():
            events.append("runtime.import.failed")
            raise RuntimeError("Owned dependency failure")

        namespace = {
            "logging": Mock(),
            "wx": SimpleNamespace(
                App=Mock(),
                CallAfter=lambda callback: callbacks.append(callback),
                ID_OK=1,
                OK=2,
                ICON_ERROR=4,
                MessageBox=Mock(),
            ),
            "startup_phase": events.append,
            "migrate_legacy_user_data": Mock(),
            "LoadBasicConfig": lambda: cfg,
            "SetConsoleVisible": Mock(),
            "SettingsDialog": Settings,
            "announce_window": lambda kind="main": events.append("window." + kind + ".ready"),
            "SaveBasicConfig": Mock(),
            "LoadRuntimeDependencies": fail_runtime,
            "translate": lambda *_args: "{error}",
            "LOCALE": {},
        }
        source = Path(__file__).resolve().parents[1] / "omnisonic" / "app.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        main = next(
            node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
        )
        exec(compile(ast.Module(body=[main], type_ignores=[]), str(source), "exec"), namespace)
        self.assertEqual(namespace["main"](), 1)
        self.assertLess(
            events.index("window.settings.ready"), events.index("runtime.import.failed")
        )
        self.assertNotIn("window.main.ready", events)
        self.assertNotIn("event_loop.begin", events)


if __name__ == "__main__":
    unittest.main()
