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

## AMD follow-up — 2026-09-12

Repeated on Windows with AMD Radeon 8060S, Python 3.12.10,
PyTorch `2.9.1+rocm7.2.1`, Transformers 5.17.0 and Accelerate 1.15.0.
The actual cached OmniVoice checkpoint was used (revision
`c5fdb5ccb189668d56333f77ba2629f4cd7535f4`), with PEFT 0.20.0 installed
in an isolated diagnostic directory, not into the running desktop environment.

- Full pytest suite: **81 passed, zero skipped**, plus 340 successful subtests.
  All five previously skipped model-dependent LoRA tests ran.
- LoRA: frozen base/trainable adapters, CPU forward/backward, a real AMD optimizer
  step, checkpoint save/resume (including restored weights and optimizer momentum),
  adapter merging and loading the resulting deployment model passed.
- Real AMD synthesis, portable preset save/load, voice cloning and a two-file
  synthesis batch passed.
- Whisper `openai/whisper-large-v3-turbo` transcribed a 52.36-second synthetic
  reference on AMD, including the final test phrase beyond the 30-second boundary.
- Invisible wx tests passed for automatic/manual transcription, stale results,
  manual edits, failure/cancellation, portable settings and batch folder structure.
- Launcher tests passed, including downloading portable CPython, building the
  ROCm source package and running Python/pip after transactional renaming.
  Power Switch transfer/rollback and batch path-quoting tests also passed.
- Ruff lint/format and the installed environment's `pip check` passed.

The first LoRA run exposed a real incompatibility: this native Windows ROCm build
has no c10d (`torch.distributed.is_available()` is false), but Accelerate 1.15's
automatic model placement imports DTensor unconditionally. Training now supplies
explicit placement through Accelerate's public API only on non-distributed builds.
It does not patch installed libraries, replace PyTorch, or claim multi-GPU support.
Distributed-capable builds retain upstream placement behavior.

Upstream warnings about optional experimental AMD attention kernels, MIOpen
workspace fallback and deprecated Transformers options were visible; these test
runs nevertheless completed successfully. Experimental kernels were not forced on.
This is a single-device regression check, not a long training/stability benchmark.
CUDA and Intel hardware were not available for a new physical-device retest here.

At the start of this audit, Whisper remained cached after its first use.
`preload_asr=false` only controlled initial loading. Optional release policies
were subsequently added as described below; automatic reference transcription
remains a separate, default-enabled setting.

## Optional model release — 2026-09-12

Added independent, default-off Whisper and OmniVoice release checkboxes, with
normalization, persistence, unsaved-change detection, reset and PL/EN labels.
Model operations acquire a model lazily and release it after the whole operation
(whole queue for batches), with no model references retained in dialog arguments
or operation results. Exception frame cleanup prevents failed workers retaining
weights. Standalone ASR avoids loading synthesis weights just to transcribe.

Real Radeon 8060S tests (`tests/smoke_model_memory.py`) passed for repeated
transcription and synthesis/reload, internal ASR during preset creation, retaining
Whisper independently, switching the release policy, errors and cancellation.
Weak references confirmed model parameters and buffers were destroyed, and
repeated cycles returned to the same allocator usage (113,246,208 bytes, 108 MiB).
Whisper loading used about 1.65–1.73 GB and OmniVoice about 2.14 GB in that process;
these are measurements for this runtime, not universal memory requirements.

The first preset-memory test found a genuine upstream retention bug:
Transformers' Higgs audio tokenizer uses an instance-keyed `lru_cache` for
`_get_conv1d_layers`, keeping tokenizer weights alive after the owning OmniVoice
object is dropped. Model release now clears that lookup cache. Prompt creation
also runs without autograd. The corrected test returned to 108 MiB after preset
creation instead of retaining roughly 919 MB. The remaining allocations were
non-Python runtime workspaces, not model tensors; tests verify both object
destruction and stable repeated allocations rather than require zero GPU usage.

`tests/test_model_lifecycle.py` covers all four policy combinations, lazy reuse,
standalone ASR, errors/cancel/retry, sample rate preservation, tokenizer-cache
retention and CPU/CUDA/ROCm/XPU cleanup dispatch without GPU dependencies; it also
runs in CI. `tests/smoke_memory_ui.py` checks invisible wx settings/save/reset,
automatic/manual ASR, all three generation tabs, preset creation, a two-file
batch, both operation-dispatch paths and the manual model toggle.

Final full regression: **95 pytest tests passed, zero skipped, 347 subtests
passed** (including the real-model LoRA tests). The existing reference/batch wx
smokes and real AMD synthesis/portable preset/clone/two-file batch smoke passed
again with the new options left off. Ruff lint/format and `pip check` also passed.

Physical release/reload validation in this follow-up is AMD-only. CUDA shares
the same PyTorch API; Intel XPU cleanup is covered by logic tests, not by a new
Intel hardware run.
