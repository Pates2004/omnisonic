"""Optional offline, real-device long-form conditioning-budget regression.

Only synthetic speech and already cached model weights are used. Retain the
unique central Workspace output as model-code regression evidence, not a backup.
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
        parser.error("Output must be inside this project's central Workspace.")
    output.mkdir(parents=True, exist_ok=False)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    started = time.monotonic()
    report = {"status": "running", "source_root": str(root), "events": [], "offline": True}

    def checkpoint(stage, **values):
        report.update(stage=stage, elapsed_seconds=round(time.monotonic() - started, 3), **values)
        report["events"].append({"stage": stage, "seconds": report["elapsed_seconds"]})
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"{stage}: {report['elapsed_seconds']}s", flush=True)

    try:
        checkpoint("loading_cached_model")
        import numpy as np
        import soundfile as sf
        import torch
        from huggingface_hub import snapshot_download

        from omnisonic.accelerator import preferred_dtype, validate_accelerator
        from omnisonic.randomness import seeded_generation
        from omnivoice import OmniVoice, OmniVoiceGenerationConfig

        accelerator = validate_accelerator(args.backend)
        snapshot = snapshot_download("k2-fsa/OmniVoice", local_files_only=True)
        model = OmniVoice.from_pretrained(
            snapshot,
            device_map=accelerator.device,
            dtype=preferred_dtype(accelerator),
            attn_implementation="sdpa",
            load_asr=False,
            local_files_only=True,
        )
        rate = int(model.sampling_rate)
        frame_rate = float(model.audio_tokenizer.config.frame_rate)
        duration = 12.0
        text = (
            "This deliberately unpunctuated paragraph tests how the speech engine divides "
            "a longer piece of text while keeping the total conditioning budget bounded "
            "and using its first generated sentence as a consistent voice reference "
            "without multiplying the requested speaking speed on every later chunk"
        )
        config = OmniVoiceGenerationConfig(
            num_step=8,
            audio_chunk_threshold=2.0,
            audio_chunk_duration=3.0,
            postprocess_output=False,
            pad_duration=0,
            fade_duration=0,
        )
        budgets = []
        real_iterative = model._generate_iterative

        def record_budget(task, gen_config):
            tokens = real_iterative(task, gen_config)
            assert all(
                int(token.shape[-1]) == size
                for token, size in zip(tokens, task.target_lens, strict=True)
            )
            budgets.extend(int(value) for value in task.target_lens)
            return tokens

        checkpoint("generating_chunked_speech", accelerator=asdict(accelerator), python=sys.version)
        with patch.object(model, "_generate_iterative", side_effect=record_budget):
            with seeded_generation(123, model.device):
                waveform = np.asarray(
                    model.generate(
                        text=text,
                        language="en",
                        duration=duration,
                        speed=1.8,
                        generation_config=config,
                    )[0],
                    dtype=np.float32,
                )
        assert len(budgets) > 1 and all(size > 0 for size in budgets), budgets
        assert sum(budgets) == int(duration * frame_rate), budgets
        assert waveform.ndim == 1 and waveform.size and np.isfinite(waveform).all()
        assert np.max(np.abs(waveform)) > 1e-4, "Output is silent"
        sf.write(output / "long-form.wav", waveform, rate, subtype="PCM_16")
        checkpoint(
            "validated",
            conditioning_frames=budgets,
            total_conditioning_frames=sum(budgets),
            frame_rate=frame_rate,
            requested_seconds=duration,
            waveform_seconds=waveform.size / rate,
            note="Conditioning budget is exact; existing chunk seams can affect final duration.",
        )
        model.release_inference_caches()
        real_iterative = None
        del model
        gc.collect()
        if accelerator.backend in {"cuda", "rocm"}:
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        elif accelerator.backend == "xpu":
            torch.xpu.synchronize()
            torch.xpu.empty_cache()
        report["status"] = "passed"
        checkpoint("completed")
        return 0
    except Exception:
        report["status"] = "failed"
        checkpoint("failed", traceback=traceback.format_exc())
        print(report["traceback"], file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
