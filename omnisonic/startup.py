"""Keep desktop startup failures visible when the console-less Python is used."""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import __version__

logger = logging.getLogger(__name__)


def startup_phase(phase: str) -> None:
    """Append a fixed diagnostic checkpoint without logging reference/user text."""
    log_path = os.environ.get("OMNISONIC_STARTUP_LOG")
    if not log_path:
        return
    try:
        if (
            not isinstance(phase, str)
            or not 1 <= len(phase) <= 80
            or not phase.isascii()
            or not phase.replace(".", "").replace("_", "").replace("-", "").isalnum()
        ):
            return
        message = f"{datetime.now(timezone.utc).isoformat()} PID={os.getpid()} phase={phase}\n"
        with Path(log_path).open("a", encoding="utf-8") as phase_file:
            phase_file.write(message)
            phase_file.flush()
    except Exception:
        # Diagnostic checkpoints must not prevent a working application from starting.
        return


def _log_runtime_metadata() -> None:
    """Identify installed packages without importing their native/model modules."""
    startup_phase("metadata.begin")
    try:
        from importlib.metadata import PackageNotFoundError, version

        versions = {}
        for package in (
            "omnisonic",
            "wxPython",
            "numpy",
            "torch",
            "torchaudio",
            "transformers",
            "sounddevice",
            "soundfile",
        ):
            try:
                versions[package] = version(package)
            except PackageNotFoundError:
                versions[package] = "not installed"
            except Exception:
                versions[package] = "unavailable"
        print(
            "Runtime metadata: "
            + json.dumps(
                {
                    "source_version": __version__,
                    "executable": sys.executable,
                    "prefix": sys.prefix,
                    "base_prefix": sys.base_prefix,
                    "packages": versions,
                },
                ensure_ascii=True,
                sort_keys=True,
            ),
            flush=True,
        )
        startup_phase("metadata.ready")
    except Exception:
        startup_phase("metadata.unavailable")


def _publish_process(path: str | None) -> None:
    if path:
        target = Path(path)
        temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(str(os.getpid()), encoding="ascii")
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Could not remove partial process marker %s: %s", temporary, exc)


def announce_window(kind: str = "main") -> None:
    _publish_process(os.environ.get("OMNISONIC_STARTUP_READY"))
    startup_phase("window." + (kind if kind in ("main", "settings") else "other") + ".ready")


def run(start_application: Callable[[], int] | None = None) -> int:
    def start() -> int:
        try:
            _publish_process(os.environ.get("OMNISONIC_STARTUP_PROCESS"))
            startup_phase("process.marker.ready")
            application = start_application
            if application is None:
                startup_phase("application.import.begin")
                from .app import main

                application = main
                startup_phase("application.import.ready")
            startup_phase("application.begin")
            status = int(application() or 0)
            startup_phase("application.returned")
            return status
        except BaseException:
            startup_phase("application.failed")
            traceback.print_exc()
            return 1

    log_path = os.environ.get("OMNISONIC_STARTUP_LOG")
    if not log_path:
        return start()

    try:
        with Path(log_path).open("a", encoding="utf-8", buffering=1) as log_file:
            with redirect_stdout(log_file), redirect_stderr(log_file):
                print(
                    f"{datetime.now(timezone.utc).isoformat()} "
                    f"PID={os.getpid()} Python={sys.version.split()[0]} "
                    f"backend={os.environ.get('OMNISONIC_ACTIVE_BACKEND', 'auto')}"
                )
                previous_handler = faulthandler.is_enabled()
                if not previous_handler:
                    faulthandler.enable(file=log_file, all_threads=True)
                try:
                    _log_runtime_metadata()
                    status = start()
                    print(f"Desktop process finished with status {status}.")
                    return status
                finally:
                    if not previous_handler:
                        faulthandler.disable()
    except OSError:
        logging.exception("Could not create the desktop startup log: %s", log_path)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
