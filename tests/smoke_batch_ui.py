"""Optional invisible wx integration test using synthetic inputs and a fake model."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


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

    class Model:
        sampling_rate = 24000

        def generate(self, **kwargs):
            assert kwargs["text"] in {"First sentence.", "Second sentence."}
            return [np.zeros(2400, dtype=np.float32)]

    app = wx.App(False)
    cfg = dict(
        DEFAULT_CONFIG, generated_audio_directory=str(scratch / "audio"), show_progress=False
    )
    frame = TestFrame(cfg, None)

    def wait_for_worker():
        deadline = time.monotonic() + 30
        while frame.current_op is not None:
            app.Yield()
            if time.monotonic() >= deadline:
                raise TimeoutError("Batch GUI worker did not finish")
            time.sleep(0.01)

    try:
        first = scratch / "one.txt"
        second = scratch / "folder" / "two.txt"
        second.parent.mkdir()
        first.write_text("First sentence.", encoding="utf-8")
        second.write_text("Second sentence.", encoding="utf-8")
        frame._scan_batch_inputs([str(first), str(second.parent)])
        wait_for_worker()
        assert frame.batch_list.GetItemCount() == 2
        frame._scan_batch_inputs([str(first)])
        wait_for_worker()
        assert frame.batch_list.GetItemCount() == 2
        frame.model = Model()
        frame.batch_mode.SetSelection(2)
        frame.notebook.SetSelection(frame.notebook.FindPage(frame.tab_batch))
        with patch.object(wx, "MessageBox", return_value=wx.OK):
            frame.OnShortcutGenerate(None)
            wait_for_worker()
        assert all(item.status == "done" for item in frame.batch_items)
        reports = list((scratch / "audio").glob("*/batch_report.json"))
        assert len(reports) == 1
        report = json.loads(reports[0].read_text())
        assert len(report["files"]) == 2
        assert all(Path(item["output"]).is_file() for item in report["files"])
        frame.batch_list.Select(0)
        frame.OnBatchRemove(None)
        assert len(frame.batch_items) == 1
        assert all(Path(item["output"]).is_file() for item in report["files"])
        print(
            "wx batch tab, deduplication, Ctrl+G, synthesis queue and non-destructive removal: OK"
        )
    finally:
        frame.Destroy()
        app.Yield()
        app.Destroy()


if __name__ == "__main__":
    main()
