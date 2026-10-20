"""Optional offline, real-device subtitle worker check with synthetic speech.

Keep the output folder as useful diagnostic evidence. It contains an artificial
reference, its matching transcript, an SRT fixture, the resulting narration,
and a report. No microphone or user audio is involved.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("cuda", "rocm", "xpu", "cpu"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from tests.materials import material_directory

    output = args.output.resolve()
    if not output.is_relative_to(material_directory("Workspace", root).resolve()):
        parser.error("The output must be inside this project's central Workspace.")
    output.mkdir(parents=True, exist_ok=False)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    started = time.monotonic()
    report = {
        "status": "running",
        "source_root": str(root),
        "output": str(output),
        "offline": True,
        "seed": 123,
        "num_step": 16,
        "events": [],
    }

    def checkpoint(stage: str, **values) -> None:
        report["stage"] = stage
        report.update(values)
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["events"].append({"stage": stage, "elapsed_seconds": report["elapsed_seconds"]})
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{stage}: {report['elapsed_seconds']:.3f}s", flush=True)

    try:
        checkpoint("checking_offline_snapshot")
        from huggingface_hub import snapshot_download

        snapshot = Path(snapshot_download(repo_id="k2-fsa/OmniVoice", local_files_only=True))
        assert (snapshot / "model.safetensors").is_file(), "Main model weights are not cached"
        assert (snapshot / "audio_tokenizer").is_dir(), "Bundled audio tokenizer is not cached"
        checkpoint("checking_accelerator", model_snapshot=str(snapshot))
        import numpy as np
        import soundfile as sf
        import torch

        import omnivoice
        from omnisonic.accelerator import preferred_dtype, validate_accelerator
        from omnisonic.batch import BatchInput
        from omnisonic.i18n import load_locales, translate
        from omnisonic.model_lifecycle import ModelLifecycle
        from omnisonic.operations import OperationState
        from omnisonic.randomness import seeded_generation
        from omnivoice import OmniVoice, OmniVoiceGenerationConfig
        from tests.test_batch_subtitles import batch_worker

        assert Path(omnivoice.__file__).resolve().is_relative_to(root / "omnivoice")
        accelerator = validate_accelerator(args.backend)
        checkpoint("loading_model", accelerator=asdict(accelerator), python=sys.version)
        model = OmniVoice.from_pretrained(
            str(snapshot),
            device_map=accelerator.device,
            dtype=preferred_dtype(accelerator),
            attn_implementation="sdpa",
            load_asr=False,
            local_files_only=True,
        )
        assert model._asr_pipe is None
        rate = int(model.sampling_rate)
        checkpoint("generating_synthetic_reference", sampling_rate=rate)
        reference_text = "This is a synthetic reference voice for a subtitle timing test."
        with seeded_generation(123, model.device):
            reference = np.asarray(
                model.generate(
                    text=reference_text,
                    language="en",
                    duration=4.0,
                    generation_config=OmniVoiceGenerationConfig(
                        num_step=16, postprocess_output=False, pad_duration=0, fade_duration=0
                    ),
                )[0],
                dtype=np.float32,
            )
        assert reference.ndim == 1 and reference.size and np.isfinite(reference).all()
        assert np.max(np.abs(reference)) > 1e-4, "Reference is silent"
        reference_path = output / "synthetic-reference.wav"
        sf.write(reference_path, reference, rate, subtype="PCM_16")
        (output / "synthetic-reference.txt").write_text(reference_text, encoding="utf-8")
        source = output / "synthetic-narration.srt"
        source.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nThe first sentence.\n\n"
            "2\n00:00:03,500 --> 00:00:06,500\nThis is the second sentence.\n",
            encoding="utf-8",
        )
        locales = load_locales((root / "langs",))
        lifecycle = ModelLifecycle(lambda *_: None, gc.collect)
        lifecycle.model = model
        state = OperationState()
        messages = []
        frame = SimpleNamespace(
            _=lambda key: translate(locales, "en", key),
            _models=lifecycle,
            Log=lambda message: messages.append(message),
            _BatchProgress=lambda *_: None,
        )
        config = OmniVoiceGenerationConfig(num_step=16)
        recorded = []
        real_generate = model.generate

        def generate_and_record(**kwargs):
            current = kwargs["generation_config"]
            assert current.postprocess_output is False
            assert current.pad_duration == 0
            assert "speed" not in kwargs
            assert kwargs["voice_clone_prompt"].ref_audio_tokens.device.type == "cpu"
            audio = np.asarray(real_generate(**kwargs)[0], dtype=np.float32)
            recorded.append((kwargs["duration"], audio.copy()))
            return [audio]

        checkpoint("preparing_reference_prompt")
        with patch.object(
            model, "create_voice_clone_prompt", wraps=model.create_voice_clone_prompt
        ) as encode_reference:
            first_prompt = lifecycle.reference_prompt(
                state, model, str(reference_path), reference_text, preprocess_prompt=True
            )
            first_prompt.validate()
            cached_prompt = lifecycle._reference_cache._entry.prompt
            assert cached_prompt.ref_audio_tokens.device.type == "cpu"
            assert (
                cached_prompt.ref_audio_tokens.data_ptr()
                != first_prompt.ref_audio_tokens.data_ptr()
            )
            del first_prompt
            checkpoint("running_real_subtitle_batch_worker")
            with patch.object(model, "generate", side_effect=generate_and_record):
                results = batch_worker()(
                    frame,
                    state,
                    model,
                    (0,),
                    output / "batch",
                    {"generation_config": config, "language": "en", "speed": 1.8},
                    (None, str(reference_path), reference_text),
                    (BatchInput(source),),
                    False,
                    123,
                )
            assert encode_reference.call_count == 1, "Reference cache was not reused"
        checkpoint("validating_waveform")
        assert len(results) == 1 and results[0].status == "done", results
        destination = Path(results[0].output)
        assert destination.name == "synthetic-narration.wav"
        info = sf.info(destination)
        assert (info.channels, info.samplerate, info.frames, info.subtype) == (
            1,
            rate,
            round(6.5 * rate),
            "PCM_16",
        ), info
        audio, actual_rate = sf.read(destination, dtype="float32")
        assert actual_rate == rate and np.isfinite(audio).all()
        for start, end in ((0, rate), (3 * rate, round(3.5 * rate))):
            assert np.all(audio[start:end] == 0), "Timeline gap is not silent"
        assert [duration for duration, _ in recorded] == [2.0, 3.0]
        for offset, (duration, generated) in zip((rate, round(3.5 * rate)), recorded, strict=True):
            assert generated.size <= round(duration * rate), "Speech exceeds its cue interval"
            assert np.max(np.abs(generated)) > 1e-4, "Subtitle speech is silent"
            expected_pcm = np.clip(generated, -1.0, 1.0 - 1 / 32768)
            np.testing.assert_allclose(
                audio[offset : offset + generated.size], expected_pcm, atol=1 / 32768, rtol=0
            )
            assert np.all(audio[offset + generated.size : offset + round(duration * rate)] == 0)
        assert config.pad_duration == 0.1 and config.postprocess_output is True
        assert (output / "batch/batch_report.json").is_file()
        report.update(
            narration=str(destination),
            frames=info.frames,
            duration_seconds=info.duration,
            subtype=info.subtype,
            reference_frames=int(reference.size),
            cue_audio_frames=[int(generated.size) for _, generated in recorded],
            reference_encodes=1,
            cached_prompt_device="cpu",
            no_speech_trimmed=True,
            initial_and_intercue_silence=True,
            messages=messages,
        )
        if accelerator.backend in {"cuda", "rocm"}:
            torch.cuda.synchronize()
        elif accelerator.backend == "xpu":
            torch.xpu.synchronize()
        checkpoint("releasing_model")
        lifecycle.release_all()
        real_generate = None
        del encode_reference, model
        lifecycle.collect_if_needed()
        if accelerator.backend in {"cuda", "rocm"}:
            torch.cuda.empty_cache()
        elif accelerator.backend == "xpu":
            torch.xpu.empty_cache()
        report["status"] = "passed"
        checkpoint("completed")
        return 0
    except Exception:
        report["status"] = "failed"
        report["traceback"] = traceback.format_exc()
        checkpoint("failed", failed_stage=report["stage"])
        print(report["traceback"], file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
