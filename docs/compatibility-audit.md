# Compatibility audit — 2026-09-09

## Bundled OmniVoice

Compared both projects against the upstream default-branch commit
[`08be0b4ccbac3e13e374e86fbfead4b4cac343e2`](https://github.com/k2-fsa/OmniVoice/commit/08be0b4ccbac3e13e374e86fbfead4b4cac343e2)
(2026-08-24), current at the audit date. Its functionality is present, including
the denoiser waveform fix. Local differences preserve CPU-aware dtype/SDPA,
validation, warning handling and previous code-quality fixes. Formatting was
excluded from the semantic comparison.

The GUI exposes voice cloning/design, automatic voices, reference transcription,
reusable prompts, languages/instructions, speed/duration, normalization and all
13 fields of `OmniVoiceGenerationConfig`. A test compares the engine dataclass
against the GUI constructor to detect omitted future generation settings.

Not every upstream developer tool has a desktop control: LoRA training/merging,
dataset preparation, evaluation and FlashInfer optimization remain CLI/API tools.
The GUI is a synthesis application, not a training interface. CUDA-only
optimizations are not enabled on AMD/Intel.

## Portable Python and accelerators

All four profiles use the same official CPython NuGet bootstrap. Backend-specific
PyTorch and runtime packages are installed according to `installer_backends.json`.

- CPU: full portable installation, imports and a real tensor test passed.
- CUDA: full portable installation and GPU validation passed on RTX 5060 Ti.
  Real synthesis, preset save/load on CPU, and synthesis with that restored
  preset also passed using the portable CUDA environment.
- ROCm: the old source-package build failure was reproduced and fixed. The
  portable package-build regression passed. Real inference on Radeon 8060S was
  confirmed by the user, not repeated on this NVIDIA audit machine.
- XPU: actual installation of Windows/Python 3.12 XPU wheels, Intel runtime
  dependencies, full application imports and `pip check` passed. GPU validation
  correctly reports that this machine has no Intel GPU; actual Intel execution
  still needs a supported Intel GPU and driver for verification.

Runtime validation is mandatory; package availability alone does not prove a
GPU/driver works. CPU fallback remains explicit. An XPU build without a usable
Intel GPU is not misidentified as the dedicated CPU build. PowerShell warnings
no longer prevent the launcher from reading structured runtime diagnostics.

Vulkan is not added: the
[ExecuTorch Vulkan backend](https://docs.pytorch.org/executorch/stable/backends/vulkan/vulkan-overview.html)
requires model export and separate runtime integration, not just an additional
PyTorch installer profile.

## Repeatable tests

- `tests/test_launcher.ps1`: selection, probe warnings and preference recovery.
- `tests/test_launcher.ps1 -Portable`: fresh Python and the ROCm build regression.
- `tests/test_power_switch.ps1`: synthetic transfers, checksums, paths, backups,
  collisions and rollback; no real user data is imported or exported by this test.
- `tests/test_batch_paths.ps1`: paths containing spaces, `!`, `&` and parentheses.
- `python -m tests.smoke_inference --backend cuda --output trash/my-inference-test`:
  optional real-device synthesis/clone test using already cached models only.

Tests reduce regression risk; they cannot guarantee zero bugs on every device,
driver release or input file.
