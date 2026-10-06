"""Regression tests for observable startup and hidden-mode diagnostics."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omnisonic.startup import announce_window, run
from omnisonic.operations import OperationState, execute_worker


class StartupTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        (root / "trash").mkdir(exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(prefix="startup-test-", dir=root / "trash"))

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


if __name__ == "__main__":
    unittest.main()
