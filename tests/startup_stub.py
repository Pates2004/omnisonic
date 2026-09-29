"""Tiny process used to check GUI startup without opening wx or loading torch."""

from __future__ import annotations

import os
import time

from omnisonic.startup import announce_window, run


def main() -> int:
    mode = os.environ.get("OMNISONIC_STARTUP_TEST_MODE", "ready")
    if mode == "ready":
        announce_window()
        time.sleep(2)
    elif mode == "fail":
        raise RuntimeError("TEST_GUI_PROCESS_EXITED_BEFORE_READY")
    elif mode == "slow":
        time.sleep(5)
    else:
        raise ValueError("Unsupported startup test mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
