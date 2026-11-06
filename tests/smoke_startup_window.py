"""Check a real first-run wx window when started through pythonw (no model)."""

from __future__ import annotations

import os
from unittest.mock import patch

from tests.materials import scratch_directory
from tests.startup_stub import assert_visible_startup


def main() -> int:
    scratch = scratch_directory("first-window-wx-")
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")
    assert_visible_startup()

    import ctypes
    from ctypes import wintypes

    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG

    kernel = ctypes.WinDLL("kernel32")
    kernel.GetConsoleWindow.restype = wintypes.HWND
    assert not kernel.GetConsoleWindow(), "pythonw unexpectedly owns a console"
    user = ctypes.WinDLL("user32")
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindowVisible.restype = wintypes.BOOL
    failures = []
    checked = []

    real_show_modal = desktop.SettingsDialog.ShowModal

    def show_modal(dialog):
        def check():
            try:
                assert dialog.is_first_run
                assert dialog.IsShownOnScreen(), "First-run dialog is not shown on screen"
                assert user.IsWindowVisible(dialog.GetHandle()), "Native dialog is hidden"
                checked.append(True)
                print("TEST_FIRST_RUN_WINDOW_VISIBLE_WITHOUT_CONSOLE", flush=True)
            except Exception as exc:
                failures.append(exc)
            finally:
                # Let the real launcher's readiness grace finish before exit.
                wx.CallLater(1300, dialog.EndModal, wx.ID_CANCEL)

        wx.CallLater(150, check)
        return real_show_modal(dialog)

    language = os.environ.get("OMNISONIC_STARTUP_TEST_LANGUAGE", "en")
    assert language in {"pl", "en"}
    cfg = dict(DEFAULT_CONFIG, language=language, first_run_done=False, hide_console=True)
    with (
        patch.object(desktop, "LoadBasicConfig", return_value=cfg),
        patch.object(desktop.SettingsDialog, "ShowModal", show_modal),
        patch.object(desktop, "SaveBasicConfig") as save,
        patch.object(desktop, "LoadRuntimeDependencies") as runtime,
    ):
        assert desktop.main() == 0
        save.assert_not_called()
        runtime.assert_not_called()
    assert checked == [True]
    assert not failures, failures
    print(
        f"Real first-run Settings ({language}) visible; no model/private settings: OK", flush=True
    )
    return 0


if __name__ == "__main__":
    from omnisonic.startup import run

    raise SystemExit(run(main))
