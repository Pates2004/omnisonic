"""Real wx timer/close lifecycle with mocked model startup and no user-data writes."""

from unittest.mock import Mock, patch


def main():
    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG

    application = wx.App(False)
    application.SetExitOnFrameDelete(False)
    failures = []

    class TestFrame(desktop.OmniVoiceFrame):
        def InitUI(self):
            self.panel = wx.Panel(self)

        def ApplyConsoleState(self):
            pass

        def ApplyTheme(self):
            pass

        def ApplyFontSize(self):
            pass

        def OnToggleModel(self, event):
            self.model_calls += 1

    class Confirmation(wx.Dialog):
        def __init__(self, parent, answer):
            super().__init__(parent, title="Close lifecycle test")
            self.answer = answer

        def ShowModal(self):
            def finish():
                try:
                    assert self.GetParent().model_calls == 0
                except Exception as error:
                    failures.append(error)
                finally:
                    self.EndModal(self.answer)

            # The original autoload is due at 500 ms, inside this nested loop.
            wx.CallLater(650, finish)
            return super().ShowModal()

    def pump(duration):
        wx.CallLater(int(duration * 1000), application.ExitMainLoop)
        application.MainLoop()

    with (
        patch.object(desktop, "ensure_user_directories"),
        patch.object(desktop, "SaveBasicConfig") as save,
    ):
        for answer in (wx.ID_NO, wx.ID_YES):
            frame = TestFrame(
                dict(DEFAULT_CONFIG, warn_exit=True, clean_temp=False, remember_ai_settings=False),
                None,
            )
            frame.model_calls = 0
            frame._CloseRecording = Mock()
            frame.OnStopAudio = Mock()
            timer = frame._autoload_timer
            with patch.object(
                wx,
                "MessageDialog",
                side_effect=lambda parent, *args, answer=answer: Confirmation(parent, answer),
            ):
                frame.Close()
            assert not timer.IsRunning()
            pump(0.9)
            if answer == wx.ID_NO:
                assert frame
                assert frame.model_calls == 1, "Autoload did not resume after cancelled close"
                save.assert_not_called()
                frame.cfg["warn_exit"] = False
                frame.Close()
                application.Yield()
            else:
                assert not frame, "Confirmed close left the native window alive"
                assert frame.model_calls == 0, "Autoload ran after the window was destroyed"
            save.reset_mock()
    assert not failures, failures
    print("Real wx autoload timer / close confirmation / destroyed frame: OK")


if __name__ == "__main__":
    main()
