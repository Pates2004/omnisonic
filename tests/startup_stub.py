"""Tiny process used to check GUI startup without opening wx or loading torch."""

from __future__ import annotations

import os
import time

from omnisonic.startup import announce_window, run


def assert_visible_startup() -> None:
    """Check native creation flags, not just the launcher's PID handshake."""
    if os.name != "nt":
        return

    import ctypes
    from ctypes import wintypes

    class StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    get_startup_info = ctypes.WinDLL("kernel32").GetStartupInfoW
    get_startup_info.argtypes = [ctypes.POINTER(StartupInfo)]
    get_startup_info.restype = None
    info = StartupInfo()
    info.cb = ctypes.sizeof(info)
    get_startup_info(ctypes.byref(info))
    print(f"TEST_GUI_WINDOW_STYLE: flags={info.dwFlags} show={info.wShowWindow}", flush=True)
    if info.dwFlags & 1 and info.wShowWindow == 0:  # STARTF_USESHOWWINDOW + SW_HIDE
        raise RuntimeError("TEST_GUI_LAUNCHED_WITH_SW_HIDE")


def main() -> int:
    mode = os.environ.get("OMNISONIC_STARTUP_TEST_MODE", "ready")
    if mode == "ready":
        assert_visible_startup()
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
