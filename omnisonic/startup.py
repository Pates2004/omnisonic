"""Keep desktop startup failures visible when the console-less Python is used."""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def _publish_process(path: str | None) -> None:
    if path:
        target = Path(path)
        temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        temporary.write_text(str(os.getpid()), encoding="ascii")
        os.replace(temporary, target)


def announce_window() -> None:
    _publish_process(os.environ.get("OMNISONIC_STARTUP_READY"))


def run(start_application: Callable[[], int] | None = None) -> int:
    _publish_process(os.environ.get("OMNISONIC_STARTUP_PROCESS"))

    def start() -> int:
        try:
            application = start_application
            if application is None:
                from .app import main

                application = main
            return int(application() or 0)
        except BaseException:
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
