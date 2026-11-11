"""Real wx shutdown, model ownership and queued workers without user-data writes."""

import gc
import argparse
import os
import threading
import weakref
from unittest.mock import Mock, patch

from tests.materials import scratch_directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "cuda:0", "xpu:0"))
    args = parser.parse_args()
    scratch = scratch_directory("shutdown-wx-")
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG

    application = wx.App(False)
    application.SetExitOnFrameDelete(False)
    failures = []
    collector = gc.collect
    tensor_factory = None
    backend = None
    baseline = 0
    if args.device:
        import torch

        from omnivoice.utils.memory import release_memory

        def collector():
            release_memory(args.device, torch)

        def tensor_factory():
            return torch.empty((512, 512), device=args.device)

        if args.device != "cpu":
            backend = getattr(torch, args.device.split(":")[0])
            backend.init()
            baseline = backend.memory_allocated(args.device)
            print(
                f"Tensor probe: torch={torch.__version__}, HIP={torch.version.hip}, "
                f"CUDA={torch.version.cuda}, device={backend.get_device_name(args.device)}",
                flush=True,
            )

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

        def _CollectModelMemory(self):
            collector()

        def Log(self, *args, **kwargs):
            pass

    class Resource:
        sampling_rate = 24000
        _asr_pipe = None

        def __init__(self):
            # Require explicit collection, not only CPython refcount teardown.
            self.cycle = self
            self.payload = tensor_factory() if tensor_factory else bytearray(1024 * 1024)

        def release_inference_caches(self):
            pass

    def populate(frame):
        frame.model = Resource()
        frame.model._asr_pipe = Resource()
        frame.audio_data = Resource()
        frame.ref_audio_data = Resource()
        if backend:
            assert backend.memory_allocated(args.device) >= baseline + 4 * 1024 * 1024
        return [
            weakref.ref(frame.model),
            weakref.ref(frame.model._asr_pipe),
            weakref.ref(frame.audio_data),
            weakref.ref(frame.ref_audio_data),
        ]

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
            resources = populate(frame) if answer == wx.ID_YES else []
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
                assert all(ref() is not None for ref in resources)
                assert frame.model_calls == 1, "Autoload did not resume after cancelled close"
                save.assert_not_called()
                resources = populate(frame)
                frame.cfg["warn_exit"] = False
                frame.Close()
                application.Yield()
                assert all(ref() is None for ref in resources), "Idle close retained model data"
            else:
                assert not frame, "Confirmed close left the native window alive"
                assert frame.model_calls == 0, "Autoload ran after the window was destroyed"
                assert all(ref() is None for ref in resources), (
                    "Confirmed close retained model data"
                )
            save.reset_mock()

        # Use the real nonmodal worker/completion queue. The frame's Python
        # wrapper remains referenced here even after its native window dies.
        frame = TestFrame(
            dict(
                DEFAULT_CONFIG,
                warn_exit=True,
                clean_temp=False,
                remember_ai_settings=False,
                show_progress=False,
            ),
            None,
        )
        frame.model_calls = 0
        frame._CloseRecording = Mock()
        frame.OnStopAudio = Mock()
        frame.prog_timer = Mock()
        frame.gauge = Mock()
        frame.btn_stop = Mock()
        resources = populate(frame)
        gate = threading.Event()
        entered = threading.Event()

        def worker(state, model):
            entered.set()
            assert gate.wait(5), "Owned test worker was never allowed to finish"
            assert model.payload is not None, "Close released a model still used by its worker"
            state.check_cancelled()

        state = frame.RunModelOperation("op_gen_title", "op_gen_msg", worker)
        assert entered.wait(5)
        with patch.object(wx, "MessageDialog") as confirmation:
            confirmation.return_value.ShowModal.return_value = wx.ID_YES
            frame.Close()
            assert frame and not frame.IsBeingDeleted()
            assert frame._close_requested and state.cancel_flag
            assert all(ref() is not None for ref in resources)
            gate.set()
            pump(1)
            assert state.finished and state.cancel_flag
            assert not frame, "Accepted close did not run after worker GUI completion"
            assert all(ref() is None for ref in resources), "Busy close retained model data"
            confirmation.assert_called_once()
            wx.CallAfter(frame._FinishRequestedClose)
            wx.CallAfter(frame._FinishRequestedClose)
            pump(0.1)  # Duplicate queued callbacks must ignore the dead native window.
    assert not failures, failures
    if backend:
        backend.synchronize(args.device)
        allocated = backend.memory_allocated(args.device)
        assert allocated <= baseline, f"Tensor storage retained after close: {allocated - baseline}"
        print(f"Actual {args.device} tensor allocation released to baseline={baseline}")
    print("Real wx idle/busy close, retained-frame model/ASR/audio release and cancellation: OK")


if __name__ == "__main__":
    main()
