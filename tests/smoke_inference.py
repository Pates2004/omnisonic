"""Optional real-device inference test; uses existing cached models only."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("cuda", "rocm", "xpu", "cpu"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"

    import numpy as np
    import soundfile as sf
    import torch

    from omnisonic.accelerator import preferred_dtype, validate_accelerator
    from omnisonic.batch import process_text_batch
    from omnisonic.operations import OperationState
    from omnivoice import OmniVoice, VoiceClonePrompt

    accelerator = validate_accelerator(args.backend)
    model = OmniVoice.from_pretrained(
        "k2-fsa/OmniVoice",
        device_map=accelerator.device,
        dtype=preferred_dtype(accelerator),
        attn_implementation="sdpa",
        load_asr=False,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    sentence = "This is a short OmniSonic compatibility test."
    generated = model.generate(text=sentence, language="en")[0]
    assert generated.size > 0 and np.isfinite(generated).all()
    sf.write(args.output / "generated.wav", generated, model.sampling_rate)
    prompt = model.create_voice_clone_prompt(
        ref_audio=(torch.as_tensor(generated).unsqueeze(0), model.sampling_rate),
        ref_text=sentence,
    )
    prompt_path = args.output / "test-voice.pt"
    prompt.save(str(prompt_path))
    restored = VoiceClonePrompt.load(str(prompt_path))
    assert restored.ref_audio_tokens.device.type == "cpu"
    cloned = model.generate(
        text="The saved voice works after loading the preset.",
        language="en",
        voice_clone_prompt=restored,
    )[0]
    assert cloned.size > 0 and np.isfinite(cloned).all()
    sf.write(args.output / "cloned.wav", cloned, model.sampling_rate)
    text_inputs = []
    for index, text in enumerate(("The first batch recording.", "The second batch recording.")):
        path = args.output / f"batch-input-{index}.txt"
        path.write_text(text, encoding="utf-8")
        text_inputs.append(path)
    results = process_text_batch(
        text_inputs,
        args.output / "batch",
        OperationState(),
        lambda text: model.generate(text=text, language="en", voice_clone_prompt=restored)[0],
        lambda path, audio: sf.write(path, audio, model.sampling_rate),
    )
    assert all(item.status == "done" for item in results)
    assert all(sf.info(item.output).frames > 0 for item in results)
    print(f"Real {accelerator.backend} inference, portable preset save/load and cloning: OK")
    print("Real two-file batch synthesis: OK")


if __name__ == "__main__":
    main()
