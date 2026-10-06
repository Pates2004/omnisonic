"""Exercise nested modal completion without network or model downloads."""

import threading
import time
from unittest.mock import patch


def main():
    import wx

    import omnisonic.app as desktop
    from omnisonic.operations import execute_worker

    application = wx.App(False)
    gate = threading.Event()
    failures = []
    checks = []

    class Confirmation(wx.Dialog):
        def __init__(self, parent, is_complete):
            super().__init__(parent, title="Test confirmation", size=(300, 150))
            self.is_complete = is_complete

        def ShowModal(self):
            deadline = time.monotonic() + 5

            def finish_confirmation():
                if not self.is_complete() and time.monotonic() < deadline:
                    wx.CallLater(20, finish_confirmation)
                    return
                try:
                    assert self.is_complete(), "Worker did not finish during confirmation"
                    assert self.GetParent().IsModal(), "Outer dialog closed below confirmation"
                    checks.append(True)
                except Exception as error:
                    failures.append(error)
                finally:
                    self.EndModal(wx.ID_YES)

            gate.set()
            wx.CallLater(20, finish_confirmation)
            return super().ShowModal()

    startup = desktop.StartupSplash(None, {"language": "en", "theme": "dark"})
    with (
        patch.object(desktop, "LoadRuntimeDependencies", side_effect=lambda: gate.wait(5)),
        patch.object(
            wx,
            "MessageDialog",
            side_effect=lambda parent, *args: Confirmation(parent, lambda: startup.finished),
        ),
    ):
        wx.CallLater(100, startup._confirm_cancel)
        assert startup.ShowModal() == wx.ID_CANCEL
    assert startup.cancel_requested
    assert checks == [True]
    assert not failures, failures

    gate = threading.Event()

    def download_worker(dialog):
        execute_worker(dialog.state, lambda state: gate.wait(5))

    def confirm_download(message, title, style, parent):
        confirmation = Confirmation(parent, lambda: download.state.finished)
        try:
            return wx.YES if confirmation.ShowModal() == wx.ID_YES else wx.NO
        finally:
            confirmation.Destroy()

    with (
        patch.object(desktop.DownloadDialog, "_run_download", download_worker),
        patch.object(wx, "MessageBox", side_effect=confirm_download),
    ):
        download = desktop.DownloadDialog(None, "Test", "Waiting", "test/model", lambda key: key)
        try:
            wx.CallLater(100, download.OnCancel, None)
            assert download.ShowModal() == wx.ID_OK
            assert download.succeeded
            assert not download.state.cancel_flag
        finally:
            gate.set()
            download.timer.Stop()
            download.Destroy()
    application.Yield()
    assert checks == [True, True]
    assert not failures, failures
    print("Startup/download nested confirmation lifecycle: OK")


if __name__ == "__main__":
    main()
