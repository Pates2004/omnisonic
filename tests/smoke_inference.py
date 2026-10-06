"""Optional real-device inference test; uses existing cached models only."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("cuda", "rocm", "xpu", "cpu"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--regression-inputs", action="store_true")
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"

    import numpy as np
    import soundfile as sf
    import torch

    from omnisonic.accelerator import preferred_dtype, validate_accelerator
    from omnisonic.batch import BatchInput, process_text_batch
    from omnisonic.operations import OperationState
    from omnivoice import OmniVoice, OmniVoiceGenerationConfig, VoiceClonePrompt

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
        text_inputs.append(BatchInput(path))
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

    if args.regression_inputs:
        from omnivoice.utils.text import normalize_text

        # A low threshold would select chunking if duration=0 were ignored.
        with patch.object(
            model, "_generate_chunked", side_effect=AssertionError("Chunking was not disabled")
        ):
            normalized = model.generate(
                text="Mam 12 jabłek.",
                language="pl",
                normalize_text=True,
                speed=None,
                generation_config=OmniVoiceGenerationConfig(
                    audio_chunk_duration=0.0, audio_chunk_threshold=0.01
                ),
            )[0]
        assert normalized.size > 0 and np.isfinite(normalized).all()
        sf.write(args.output / "normalized.wav", normalized, model.sampling_rate)
        # CFG=0 is a valid no-guidance mode but can produce near-silence. Verify
        # raw decoding separately: silence trimming may correctly reject it.
        cfg_zero = model.generate(
            text=sentence,
            language="en",
            voice_clone_prompt=restored,
            generation_config=OmniVoiceGenerationConfig(
                guidance_scale=0.0, audio_chunk_duration=0.0, postprocess_output=False
            ),
        )[0]
        assert cfg_zero.size > 0 and np.isfinite(cfg_zero).all()
        sf.write(args.output / "cfg-zero-raw.wav", cfg_zero, model.sampling_rate)
        reference_paths = [str(args.output / "generated.wav"), str(args.output / "cloned.wav")]
        transcripts = [sentence, "The saved voice works after loading the preset."]
        with patch.object(
            model, "create_voice_clone_prompt", wraps=model.create_voice_clone_prompt
        ) as create_prompt:
            paired = model.generate(
                text=["The first reference voice.", "The second reference voice."],
                language="en",
                ref_audio=reference_paths,
                ref_text=transcripts,
                speed=[None, 1.0],
                audio_chunk_duration=0.0,
            )
        assert len(paired) == 2
        assert [
            call.kwargs["ref_audio"] for call in create_prompt.call_args_list
        ] == reference_paths
        assert [call.kwargs["ref_text"] for call in create_prompt.call_args_list] == transcripts
        for index, audio in enumerate(paired):
            assert audio.size > 0 and np.isfinite(audio).all()
            sf.write(args.output / f"paired-reference-{index}.wav", audio, model.sampling_rate)
        (args.output / "regression-inputs.json").write_text(
            json.dumps(
                {
                    "backend": accelerator.backend,
                    "device": accelerator.name,
                    "torch": torch.__version__,
                    "normalized_polish": normalize_text("Mam 12 jabłek.", language="pl"),
                    "cfg_zero_raw_decoding": "passed",
                    "cfg_zero_rms": float(np.sqrt(np.mean(np.square(cfg_zero)))),
                    "disabled_chunking": "passed",
                    "optional_speed": "passed",
                    "paired_references": "passed",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print("Real normalization, CFG zero, disabled chunking and paired references: OK")


if __name__ == "__main__":
    main()
