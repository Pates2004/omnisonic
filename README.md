# OmniSonic 🎧

OmniSonic is an accessible Windows desktop application for the
[OmniVoice](https://github.com/k2-fsa/OmniVoice) multilingual text-to-speech
engine. It provides voice cloning, voice design, automatic voice generation,
microphone recording, reusable private presets, and Polish/English interfaces.

## Najważniejsze funkcje / Highlights

- native wxPython interface designed for keyboard and NVDA use;
- voice cloning from WAV, FLAC, OGG, Opus, MP3, AIFF, AU, or CAF references,
  with optional ASR transcription;
- automatic and attribute-based voice design, including supported Chinese
  dialects and additional voice instructions;
- pause, resume, stop, recording, manual save, and configurable auto-save;
- a dedicated preset manager with create, rename, rebuild, and delete actions;
- portable voice presets stored in the application's ignored `presets/` directory;
- full access to OmniVoice's generation and long-form audio parameters;
- lazy ASR loading to reduce startup time and memory use;
- Polish and English localization.

## Wymagania / Requirements

- Windows 10 or newer;
- Windows PowerShell 5.1 (included with supported Windows versions);
- a 64-bit Python 3.10-3.13 installation is optional;
- a supported NVIDIA, AMD, or Intel GPU is recommended for practical generation speed;
- a working audio output device; microphone access is required only for recording.

The launcher selects and verifies one of four first-class acceleration profiles:

- NVIDIA GPU -> CUDA;
- supported AMD Radeon/Ryzen AI GPU on Windows 11 -> native Windows ROCm;
- supported Intel Arc/Core Ultra Arc GPU on Windows 11 -> XPU;
- everything else, or an explicit fallback -> CPU.

Automatic priority on multi-GPU computers is CUDA, ROCm, XPU, then CPU. Merely
finding an AMD or Intel display adapter is not enough: Auto mode checks the
supported-hardware patterns in `installer_backends.json`, then validates the
installed runtime with a real tensor operation. CPU inference can be very slow.
WAV, FLAC, OGG/Vorbis, OGG/Opus, AIFF, AU, and CAF are decoded by the bundled
audio stack without a separate FFmpeg installation. MP3 is supported by current
bundled builds as well; uncommon formats can use the fallback decoder and may
require [FFmpeg](https://ffmpeg.org/download.html) on `PATH`.

## Instalacja i uruchomienie / Install and run

The recommended one-click path is:

```text
start_desktop.bat
```

On a fresh installation the launcher offers two isolated modes: its own
portable Python 3.12.10 in `env/` (recommended), or `venv/` based on a compatible
system Python. It remembers the choice, installs the backend-specific PyTorch
build before the rest of the application, verifies dependencies and imports,
and executes a real accelerator matrix multiplication. A damaged environment is
repaired on the next launch.

Portable mode uses the official [CPython NuGet package](https://www.nuget.org/packages/python/3.12.10),
verified with SHA-256. It does not install Python globally or modify system PATH.
Unlike the former embedded ZIP, it supports pip's isolated package builds,
including ROCm's source package. The old `Cannot import 'setuptools.build_meta'`
error was a launcher bootstrap bug, not a missing HIP SDK. Updating the launcher
and retrying `start_desktop.bat -Mode Portable` repairs an incomplete installation;
there is no need to delete the whole application or replace a working system-Python setup.

Regular launches check hardware, declared package versions, and a real accelerator
operation, but no longer import the entire application and run `pip check` before
starting it a second time. Full validation runs during installation, with
`-InstallOnly`, or once after installer inputs/hardware change. A stale marker alone
does not trigger a new download: a working runtime is validated and reused.

AMD ROCm is enabled as a supported profile, including the Radeon 8060S; support
still depends on the GPU, Windows, and driver requirements in the backend matrix.
The installer supplies the profile's ROCm SDK Python packages inside its private
environment. Install a compatible AMD graphics driver as described in
[AMD's Windows installation guide](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/install/installryz/windows/install-pytorch.html).
A separate system-wide HIP SDK does not fix Python package-build isolation errors.

Runtime replacement is transactional. The launcher prepares and validates
`env.new/` or `venv.new/` before activating it, and keeps the previously working
runtime as `env.old/` or `venv.old/`. A failed staging install never replaces the
active environment.

The mode can be changed explicitly with `start_desktop.bat -Mode Portable` or
`start_desktop.bat -Mode System`. `start_desktop.bat -InstallOnly` installs and
validates everything without opening the desktop application.

Normal installations should leave backend selection on Auto. Overrides are
available for repair, testing, and mixed-GPU computers:

```text
start_desktop.bat -Backend Auto
start_desktop.bat -Backend CUDA
start_desktop.bat -Backend ROCm
start_desktop.bat -Backend XPU
start_desktop.bat -Backend CPU
```

The same values can be supplied through `OMNISONIC_BACKEND`. Priority is CLI,
environment variable, saved CLI preference, then hardware autodetection. An
accelerator failure offers Retry, CPU, diagnostic details, or Abort; fallback to
CPU is never silent. ROCm currently requires Python 3.12, so portable Python
3.12.10 is selected when a compatible system interpreter is unavailable.

When **Hide launcher console** is enabled, normal launches are handed off to
`pythonw.exe` so the console does not remain open with the application. The
launcher keeps its console available during first-time installation and shows
it again if startup or environment repair fails. Restart OmniSonic after
changing this option so the launcher can select the correct Python executable.

The **System** settings tab shows the active backend, device, PyTorch/TorchAudio
versions, CUDA/HIP/XPU state, Python, OS, and RAM. **Copy diagnostics** places a
report suitable for a bug submission on the clipboard.

Keyboard shortcuts can be edited on the **Keyboard shortcuts** settings tab.
Each command can be enabled independently, all shortcuts can be disabled with
one global checkbox, and the default assignments can be restored at any time.
`Ctrl+Shift+S` creates a preset from the reference audio currently loaded on
the **Voice Clone** tab and asks for its name.

In the settings dialog, Enter activates **Save** and Escape cancels. Escape
closes immediately when nothing changed and asks before discarding unsaved
changes otherwise.

Manual setup:

```powershell
python -m venv venv
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\python -m pip install -e ".[desktop]"
venv\Scripts\python -m omnisonic.app
```

Manual pip setup uses normal dependency resolution and does not provide the
launcher's hardware-specific build selection. Use `start_desktop.bat` for the
supported universal Windows installation path. Binary backend versions and
official package sources are maintained only in `installer_backends.json`; the
project metadata no longer forces CUDA or any other binary PyTorch variant.

After installation, the `omnisonic` command is also available.

## Dane prywatne / Private data

### Batch text-to-speech

On **Batch processing**, use **Add files** or **Add folders** to select one or
many TXT/Markdown inputs. Folder selection supports multiple folders at once;
subfolder scanning is optional. Duplicate paths are skipped. UTF-8 (with or
without BOM) and UTF-16 with BOM are supported; Markdown is read as plain text.
Binary documents such as PDF/DOCX and audio inputs are not treated as text.

Choose Clone, Design, or Automatic mode. The batch uses the voice/preset,
language/instructions and advanced settings from the corresponding main tab.
With Clone mode, the same reference prompt is prepared once and reused for the
whole batch. In Automatic/Design mode the engine can choose a different voice
for each file; use a cloned preset when speaker consistency is required.

**Process files** (or **Ctrl+G** while this tab is active) processes files in
sequence, keeping GPU memory use bounded. Each input produces a separate WAV
inside a new batch subfolder of the chosen output directory, along with
`batch_report.json`. Matching names from different folders do not overwrite one
another. This explicit batch destination bypasses the single-file save prompts.
Saving a new generated-audio directory in Settings immediately updates the batch
destination, without restarting the app. Unrelated settings leave a manually
chosen batch directory unchanged. A running batch keeps its original destination;
the updated folder applies to the next batch.

Enable **Preserve input folder structure** to keep each selected folder's name
and its subfolders inside the batch output, for example:
`Book/Chapter 1/part.txt` becomes `batch-.../Book/Chapter 1/part.wav`.
With multiple selected folders, each gets its own output tree. Individually
added files go directly into the batch directory. Duplicate folder or WAV names
get a numeric suffix instead of overwriting or merging unrelated inputs. If
selections overlap, a file is queued once using its first selection's origin.
Only folders containing queued text files are recreated; empty folders and
unrelated files are not copied. **Include subfolders** controls scanning, while
this new checkbox controls output layout and can be changed after scanning.
It is off by default, preserving the flat, numbered output layout.

Bad files are reported and remaining files continue. Cancellation waits for the
current model call and keeps completed recordings. Retrying skips completed
queue entries; Delete/**Remove selected** only remove entries from the queue,
not source files or saved audio. The queue is session-only. Limits are 5000
files per queue and 5 MiB of text per file.

### Power Switch: transfer to another PC or change the GPU

Close OmniSonic, then run `power_switch.bat`. It needs only Windows PowerShell,
not an installed Python environment. The menu offers:

- **Change backend**: Auto, CUDA, ROCm, XPU, or CPU through the normal transactional
  installer. Settings, presets and audio stay in place. Failed repair does not
  replace the saved working Python/backend choice.
- **Export**: settings (including shortcuts), the entire `presets/` folder, and
  optionally saved audio from both configured audio directories.
- **Import**: restore an exported folder. Existing extra presets remain; matching
  files/settings are backed up before replacement.

Copy the whole export folder from `power-switch-backups/` to the destination PC,
then select Import there. Exports/backups contain private voice data and are
ignored by Git. They are never automatically deleted. Import verifies SHA-256,
rejects traversal paths and links/junctions, and rolls back failed file copies.

Import remaps output folders to the destination user's actual Windows Documents
location: `OmniSonic/generated` and `OmniSonic/record`. Python, drivers, cached
models, temporary microphone references and old backend preferences are not
transferred. Use **Change backend -> Auto** after import, then start normally.
Model weights may need downloading on the destination PC.

```bat
power_switch.bat -Action Switch -Backend Auto
power_switch.bat -Action Export -IncludeAudio
power_switch.bat -Action Import -ProfilePath "D:\My OmniSonic profile"
```

See [the compatibility audit](docs/compatibility-audit.md) for the checked
OmniVoice revision, GUI feature coverage and hardware-test limitations.

Voice presets are stored in the portable `presets/` directory next to the
application. This makes it possible to move or back up the program together
with all saved voices. Settings and temporary recordings remain under the
user's OmniSonic application-data directory (normally
`%LOCALAPPDATA%\OmniSonic`). No other preset location is scanned or migrated.

Voice presets contain derived voice tokens and may contain a reference
transcript. Treat them as private data. The complete `presets/` tree is ignored
by Git.

The **Voice Presets** tab is the only place where presets can be removed. Delete
shows the configured warning, while Shift+Delete removes the selected preset
without that warning. Editing can rename a preset, update its transcript, or
rebuild its voice data from a new source recording. The original audio path is
not embedded in a preset, so choosing a replacement file during editing is
optional.

Generated and recorded WAV files default to
`Documents\OmniSonic\generated` and `Documents\OmniSonic\record`. Both folders
can be entered directly or selected with **Browse** in settings. The related
checkbox chooses between saving directly to that configured folder and asking
for a destination each time.

## Development

```powershell
venv\Scripts\python -m pip install -e ".[desktop,dev]"
venv\Scripts\python -m ruff check omnisonic tests
venv\Scripts\python -m pytest
```

Fast tests for configuration, localization, validation, and operation state do
not require downloading the AI model:

```powershell
venv\Scripts\python -m unittest -v tests.test_desktop_logic
```

Model-dependent LoRA tests require `OMNIVOICE_TEST_MODEL_PATH` to point to a
local OmniVoice checkpoint.

`powershell -File tests/test_launcher.ps1` tests startup decisions without a GPU.
Add `-Portable` to download the official portable Python and build the small ROCm
source package that previously failed. This network regression also tests Python
after environment activation/renaming; it leaves its diagnostic files in `trash/`.

## Project structure

- `omnisonic/` — desktop application, configuration, localization, and UI state;
- `omnivoice/` — bundled upstream TTS engine, training, evaluation, and CLI tools;
- `langs/` — Polish and English desktop translations;
- `tests/` — lightweight desktop tests and optional model integration tests;
- `start_desktop.bat` / `desktop_launcher.ps1` — verified Windows launcher,
  Python bootstrap, installer, and repair entry point.
- `installer_backends.json` — the single source of truth for CUDA, ROCm, XPU,
  and CPU PyTorch builds and supported automatic hardware selection;
- `omnisonic/accelerator.py` — backend-neutral runtime selection, smoke tests,
  and diagnostics used by both the launcher and desktop application.

## Credits and license

- OmniSonic desktop application: Pates2004;
- OmniVoice engine: Han Zhu and the
  [k2-fsa OmniVoice contributors](https://github.com/k2-fsa/OmniVoice).

Licensed under Apache-2.0. See [LICENSE](LICENSE).
