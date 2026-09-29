"""Regression tests for observable startup and hidden-mode diagnostics."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omnisonic.startup import announce_window, run


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


if __name__ == "__main__":
    unittest.main()
