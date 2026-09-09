"""Optional invisible wx integration test using synthetic inputs and a fake model."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


def main():
    root = Path(__file__).resolve().parents[1]
    scratch = Path(tempfile.mkdtemp(prefix="batch-ui-", dir=root / "trash"))
    os.environ["OMNISONIC_DATA_DIR"] = str(scratch / "settings")
    os.environ["OMNISONIC_APP_DIR"] = str(scratch / "program")

    import numpy as np
    import wx

    import omnisonic.app as desktop
    from omnisonic.config import DEFAULT_CONFIG

    desktop.OmniVoiceGenerationConfig = SimpleNamespace

    class TestFrame(desktop.OmniVoiceFrame):
        def AutoLoadModel(self):
            pass

        def ApplyConsoleState(self):
            pass

    generation_started = threading.Event()
    release_generation = threading.Event()

    class Model:
        sampling_rate = 24000

        def generate(self, **kwargs):
            assert kwargs["text"] in {"First sentence.", "Second sentence."}
            generation_started.set()
            if not release_generation.wait(30):
                raise TimeoutError("Test did not release the batch model")
            return [np.zeros(2400, dtype=np.float32)]

    app = wx.App(False)
    cfg = dict(
        DEFAULT_CONFIG, generated_audio_directory=str(scratch / "audio"), show_progress=False
    )
    frame = TestFrame(cfg, None)
    assert frame.batch_recursive.GetValue()
    assert frame.batch_preserve_structure.GetValue()
    frame.batch_preserve_structure.SetValue(False)

    def change_output_setting(directory):
        dialog = Mock(cfg=dict(frame.cfg, generated_audio_directory=str(directory)))
        dialog.ShowModal.return_value = wx.ID_OK
        with patch.object(desktop, "SettingsDialog", return_value=dialog):
            frame.OnOpenSettings(None)
        assert frame.batch_output.GetValue() == str(directory)

    def wait_for_worker():
        deadline = time.monotonic() + 30
        while frame.current_op is not None:
            app.Yield()
            if time.monotonic() >= deadline:
                raise TimeoutError("Batch GUI worker did not finish")
            time.sleep(0.01)

    try:
        first = scratch / "one.txt"
        second = scratch / "folder" / "nested" / "two.txt"
        second.parent.mkdir(parents=True)
        first.write_text("First sentence.", encoding="utf-8")
        second.write_text("Second sentence.", encoding="utf-8")
        frame._scan_batch_inputs([str(first), str(second.parent.parent)])
        wait_for_worker()
        assert frame.batch_list.GetItemCount() == 2
        frame._scan_batch_inputs([str(first)])
        wait_for_worker()
        assert frame.batch_list.GetItemCount() == 2
        frame.model = Model()
        frame.batch_mode.SetSelection(2)
        frame.notebook.SetSelection(frame.notebook.FindPage(frame.tab_batch))
        active_output = scratch / "changed-before-start"
        next_output = scratch / "changed-while-processing"
        change_output_setting(active_output)
        with patch.object(wx, "MessageBox", return_value=wx.OK):
            frame.OnShortcutGenerate(None)
            # Cold imports of the inference libraries can take longer than synthesis.
            assert generation_started.wait(50), "Batch did not start"
            change_output_setting(next_output)
            release_generation.set()
            wait_for_worker()
        assert all(item.status == "done" for item in frame.batch_items)
        reports = list(active_output.glob("*/batch_report.json"))
        assert len(reports) == 1
        assert not next_output.exists()
        report = json.loads(reports[0].read_text())
        assert len(report["files"]) == 2
        assert all(Path(item["output"]).is_file() for item in report["files"])
        assert all(Path(item["output"]).parent == reports[0].parent for item in report["files"])
        frame.batch_list.Select(0)
        frame.OnBatchRemove(None)
        assert len(frame.batch_items) == 1
        assert all(Path(item["output"]).is_file() for item in report["files"])
        frame._scan_batch_inputs([str(first)])
        wait_for_worker()
        with patch.object(wx, "MessageBox", return_value=wx.OK):
            frame.OnShortcutGenerate(None)
            wait_for_worker()
        assert len(list(next_output.glob("*/*.wav"))) == 1
        assert all(Path(item["output"]).is_file() for item in report["files"])

        # The checkbox may be enabled after scanning and survives progress updates.
        frame.OnBatchClear(None)
        book = scratch / "Book"
        nested = book / "Chapter 1" / "part.txt"
        nested.parent.mkdir(parents=True)
        nested.write_text("First sentence.", encoding="utf-8")
        other = scratch / "Notes" / "note.md"
        other.parent.mkdir()
        other.write_text("Second sentence.", encoding="utf-8")
        frame._scan_batch_inputs([str(book), str(other.parent)])
        wait_for_worker()
        assert not frame.batch_preserve_structure.GetValue()
        frame.batch_preserve_structure.SetValue(True)
        with patch.object(wx, "MessageBox", return_value=wx.OK):
            frame.OnShortcutGenerate(None)
            assert not frame.batch_preserve_structure.IsEnabled()
            wait_for_worker()
        assert frame.batch_preserve_structure.IsEnabled()
        assert all(item.status == "done" for item in frame.batch_items)
        paths = [Path(item.output) for item in frame.batch_items]
        assert paths[0].relative_to(paths[0].parents[2]) == Path("Book/Chapter 1/part.wav")
        assert paths[1].relative_to(paths[1].parents[1]) == Path("Notes/note.wav")
        assert frame.batch_items[0].source_root == str(book)
        assert all(path.is_file() for path in paths)
        print("wx batch tab, live settings, fixed running output, Ctrl+G and safe removal: OK")
        print("wx preserve-folder checkbox, nested/multiple folders and retained origins: OK")
    finally:
        release_generation.set()
        with patch.object(wx, "MessageBox", return_value=wx.OK):
            wait_for_worker()
        frame.Destroy()
        app.Yield()
        app.Destroy()


if __name__ == "__main__":
    main()
