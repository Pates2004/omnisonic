"""Exercise recording recovery and keyboard state with a synthetic input stream."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch


def main():
    root = Path(__file__).resolve().parents[1]
    scratch = Path(tempfile.mkdtemp(prefix="recording-ui-", dir=root / "trash"))
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import numpy as np
    import soundfile as sf
    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG
    from omnisonic.operations import OperationState

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

    application = wx.App(False)
    stream = Mock(samplerate=44100)
    sound = Mock()
    sound.InputStream.return_value = stream
    frame = TestFrame(
        dict(DEFAULT_CONFIG, language="pl", warn_exit=False, remember_ai_settings=False), None
    )
    application.SetTopWindow(frame)
    try:
        with (
            patch.object(desktop, "np", np),
            patch.object(desktop, "sf", sf),
            patch.object(desktop, "sd", sound),
            patch.object(wx, "MessageBox", return_value=wx.OK),
        ):
            frame.OnShortcutRecord(None)
            assert frame.btn_rec_ref.GetLabel() == frame._("stop_rec")
            assert frame._("stop_rec") in frame.item_record.GetItemLabel()
            assert frame.btn_rec_ref.IsEnabled()
            assert frame.item_record.IsEnabled()
            assert not frame.btn_gen_clone.IsEnabled()
            callback = sound.InputStream.call_args.kwargs["callback"]
            callback(np.full((441, 1), 0.25, dtype=np.float32), 441, None, None)

            with patch.object(desktop, "atomic_write", side_effect=PermissionError("test failure")):
                frame.OnShortcutRecord(None)
            assert frame.rec_stream is None
            assert len(frame.rec_data) == 1
            assert frame.btn_rec_ref.GetLabel() == frame._("record_retry_save")
            assert frame._("record_retry_save") in frame.item_record.GetItemLabel()
            assert frame.btn_rec_ref.IsEnabled()
            assert not frame.item_generate.IsEnabled()

            with patch.object(wx, "FileDialog") as picker:
                dialog = picker.return_value.__enter__.return_value
                dialog.ShowModal.return_value = wx.ID_CANCEL
                frame.OnShortcutRecord(None)
            assert len(frame.rec_data) == 1
            assert sound.InputStream.call_count == 1

            destination = scratch / "recovered.wav"
            with patch.object(wx, "FileDialog") as picker:
                dialog = picker.return_value.__enter__.return_value
                dialog.ShowModal.return_value = wx.ID_OK
                dialog.GetPath.return_value = str(destination)
                frame.OnShortcutRecord(None)
            assert sf.info(destination).samplerate == 44100
            assert sf.info(destination).frames == 441
            assert not frame.rec_data
            assert frame.clone_ref_audio.GetValue() == str(destination)
            assert frame.btn_rec_ref.GetLabel() == frame._("rec_ref")
            assert frame._("menu_record") in frame.item_record.GetItemLabel()
            assert frame.btn_gen_clone.IsEnabled()

            frame.current_op = OperationState()
            frame._set_operation_controls_enabled(False)
            frame.OnShortcutRecord(None)
            assert sound.InputStream.call_count == 1
            assert not frame.btn_rec_ref.IsEnabled()
            frame.current_op = None
            frame._set_operation_controls_enabled(True)

            frame.rec_data = [np.full((441, 1), 0.25, dtype=np.float32)]
            frame._UpdateRecordingControls(frame.btn_rec_ref)
            with patch.object(wx, "MessageDialog") as confirmation:
                confirmation.return_value.ShowModal.return_value = wx.ID_NO
                event = wx.CloseEvent(wx.wxEVT_CLOSE_WINDOW)
                frame.OnCloseWindow(event)
                assert event.GetVeto()
                assert len(frame.rec_data) == 1
                assert confirmation.call_args.args[1] == frame._("record_discard_close")
        print("Synthetic microphone, native rate, save recovery, shortcuts and discard warning: OK")
    finally:
        if frame._autoload_timer:
            frame._autoload_timer.Stop()
        if frame._reference_timer:
            frame._reference_timer.Stop()
        frame.Destroy()
        application.Yield()
        application.Destroy()


if __name__ == "__main__":
    main()
