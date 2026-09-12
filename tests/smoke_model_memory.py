"""Real-device model release/reload checks, using cached models and a test WAV."""

from __future__ import annotations

import argparse
import json
import os
import weakref
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("cpu", "cuda", "rocm", "xpu"), required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["HF_HUB_OFFLINE"] = "1"

    import numpy as np
    import soundfile as sf
    import torch

    from omnisonic.accelerator import preferred_dtype, validate_accelerator
    from omnisonic.model_lifecycle import ModelLifecycle
    from omnisonic.operations import OperationState, execute_worker
    from omnivoice import OmniVoice, VoiceClonePrompt
    from omnivoice.models.omnivoice import WhisperASR
    from omnivoice.utils.memory import release_memory

    info = validate_accelerator(args.backend)
    gpu = getattr(torch, info.device.split(":")[0], None) if info.device != "cpu" else None
    reference, sr = sf.read(args.reference, dtype="float32", always_2d=True)
    reference = reference[: sr * 10].mean(axis=1)
    asr_name = "openai/whisper-large-v3-turbo"
    models, whispers, readings = [], [], []
    model_weights, whisper_weights = [], []

    def snapshot(label):
        if gpu:
            gpu.synchronize()
        result = {
            "phase": label,
            "allocated": gpu.memory_allocated() if gpu else 0,
            "reserved": gpu.memory_reserved() if gpu else 0,
        }
        readings.append(result)
        print(json.dumps(result), flush=True)
        return result["allocated"]

    def factory(state):
        model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map=info.device,
            dtype=preferred_dtype(info),
            attn_implementation="sdpa",
            load_asr=False,
            asr_device=info.device,
        )
        models.append(weakref.ref(model))
        model_weights.extend(weakref.ref(tensor) for tensor in model.parameters())
        model_weights.extend(weakref.ref(tensor) for tensor in model.buffers())
        snapshot("OmniVoice loaded")
        return model

    runtime = ModelLifecycle(
        factory,
        lambda: release_memory(info.device, torch),
        lambda cfg: WhisperASR(asr_name, info.device),
    )
    settings = dict(
        asr_model_name=asr_name,
        unload_asr_after_transcription=True,
        unload_omnivoice_after_operation=True,
    )
    snapshot("baseline")

    def released(label):
        runtime.collect_if_needed()
        remaining = snapshot(label)
        assert all(ref() is None for ref in models), "OmniVoice object is still retained"
        assert all(ref() is None for ref in whispers), "Whisper object is still retained"
        assert all(ref() is None for ref in model_weights + whisper_weights), "Weights retained"
        # HIP BLAS/MIOpen keep non-tensor C++ workspaces after first use. Check
        # actual model destruction, a substantial drop and stable repeated
        # cycles instead of incorrectly requiring the driver to use zero bytes.
        last_loaded = next(
            r["allocated"] for r in reversed(readings) if r["phase"].endswith("loaded")
        )
        if gpu:
            assert remaining < last_loaded - 256 * 1024**2, "Model-sized memory was not released"
        return remaining

    def run(worker, *, transcription=False, cfg=None):
        state = OperationState()
        execute_worker(
            state,
            runtime.run_transcription if transcription else runtime.run,
            cfg or settings,
            worker,
        )
        runtime.collect_if_needed()
        return state

    def transcribe(state, model):
        if model._asr_pipe is None:
            model.load_asr_model()
        whispers.append(weakref.ref(model._asr_pipe.model))
        whisper_weights.extend(weakref.ref(tensor) for tensor in model._asr_pipe.model.parameters())
        whisper_weights.extend(weakref.ref(tensor) for tensor in model._asr_pipe.model.buffers())
        snapshot("Whisper loaded")
        result = model.transcribe((reference, sr))
        assert result.strip()
        if model.unload_asr_after_transcription:
            assert model._asr_pipe is None
        return result

    # No synthesis model is needed for either standalone transcription.
    previous = None
    for index in range(2):
        state = run(transcribe, transcription=True)
        assert state.succeeded, state.error
        assert not models
        assert all(ref() is None for ref in whispers)
        remaining = released(f"Whisper released {index + 1}")
        if previous is not None:
            assert remaining <= previous + 1024**2, "Repeated ASR cycles leak memory"
        previous = remaining

    def generate(state, model):
        result = model.generate(text="This is a memory release test.", language="en")[0]
        assert result.size and np.isfinite(result).all()
        return result

    previous = None
    for index in range(2):
        state = run(generate)
        assert state.succeeded, state.error
        sf.write(args.output / f"generated-{index}.wav", state.result, runtime.sampling_rate)
        remaining = released(f"OmniVoice released {index + 1}")
        if previous is not None:
            assert remaining <= previous + 1024**2, "Repeated synthesis cycles leak memory"
        previous = remaining
    assert len(models) == 2

    # Internal ASR during preset creation must obey the same immediate policy.
    def save_prompt(state, model):
        prompt = model.create_voice_clone_prompt(ref_audio=(torch.from_numpy(reference)[None], sr))
        if model.unload_asr_after_transcription:
            assert model._asr_pipe is None
        prompt.save(str(args.output / "test-preset.pt"))
        return prompt.ref_text

    assert run(save_prompt).succeeded
    released("Preset creation released both models")
    restored = VoiceClonePrompt.load(str(args.output / "test-preset.pt"))
    assert restored.ref_audio_tokens.device.type == "cpu"
    assert restored.ref_text.strip()

    # Keep Whisper independently while releasing the main model.
    keep_asr = dict(settings, unload_asr_after_transcription=False)
    assert run(save_prompt, cfg=keep_asr).succeeded
    assert runtime.model is None and runtime.asr_pipe is not None
    assert all(ref() is None for ref in models)
    pipe_id = id(runtime.asr_pipe)
    snapshot("Whisper retained without OmniVoice")
    assert run(transcribe, transcription=True, cfg=keep_asr).succeeded
    assert id(runtime.asr_pipe) == pipe_id
    assert run(transcribe, transcription=True).succeeded
    released("Retained Whisper released after policy change")

    def fail_after_generation(state, model):
        generate(state, model)
        raise ValueError("Intentional memory test failure")

    failed = run(fail_after_generation)
    assert isinstance(failed.error, ValueError)
    released("Failed generation released model despite retained error")

    def cancel_after_asr_load(state, model):
        model.load_asr_model()
        state.request_cancel()
        state.check_cancelled()

    assert run(cancel_after_asr_load, transcription=True).cancel_flag
    released("Cancelled transcription released model")
    (args.output / "report.json").write_text(
        json.dumps({"backend": info.backend, "device": info.name, "readings": readings}, indent=2),
        encoding="utf-8",
    )
    print("Real model release, reload, independent ASR, presets, errors and cancellation: OK")


if __name__ == "__main__":
    main()
