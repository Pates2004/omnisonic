"""Optional real-device Whisper regression with synthetic speech longer than 30s."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", default="rocm")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.output.resolve() / "long-reference.wav"
    os.environ["OMNISONIC_ASR_TEST_WAV"] = str(source)
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Add-Type -AssemblyName System.Speech; "
            "$speech = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$speech.Rate = -1; "
            "$speech.SetOutputToWaveFile($env:OMNISONIC_ASR_TEST_WAV); "
            "try { foreach ($number in 1..10) { "
            "$speech.Speak('This is a reference recording for a local transcription test.'); "
            "}; $speech.Speak('The final password is yellow elephant.') } "
            "finally { $speech.Dispose() }",
        ],
        check=True,
        timeout=60,
    )
    import numpy as np
    import soundfile as sf
    import torch

    from omnisonic.accelerator import validate_accelerator
    from omnivoice import OmniVoice

    fake_pipe = Mock(return_value={"text": " stereo transcript "})
    stereo = np.array([[0.2, 0.4], [0.6, 0.8]], dtype=np.float32)
    assert (
        OmniVoice.transcribe(SimpleNamespace(_asr_pipe=fake_pipe), (stereo, 16000))
        == "stereo transcript"
    )
    np.testing.assert_allclose(fake_pipe.call_args.args[0]["array"], [0.4, 0.6])
    assert fake_pipe.call_args.kwargs == {"return_timestamps": True}

    accelerator = validate_accelerator(args.backend)
    audio, sr = sf.read(source, dtype="float32")
    assert len(audio) / sr > 35, "Fixture must exercise long-form Whisper"
    # The actual engine methods, without allocating the unused synthesis model.
    model = SimpleNamespace(
        _asr_model_name="openai/whisper-large-v3-turbo",
        _asr_device=accelerator.device,
        device=torch.device(accelerator.device),
    )
    OmniVoice.load_asr_model(model)
    assert str(model._asr_pipe.device) == accelerator.device
    result = OmniVoice.transcribe(model, (audio, sr))
    assert "yellow elephant" in result.lower(), result
    report = {
        "backend": accelerator.backend,
        "device": accelerator.name,
        "asr_device": str(model._asr_pipe.device),
        "duration": len(audio) / sr,
        "text": result,
    }
    (args.output / "asr-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
