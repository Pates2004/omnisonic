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

The launcher isolates Python path/startup settings for its child processes, but
preserves pip proxy, certificate, index and security policies. It rejects pip
settings that redirect installation or select another interpreter, with an
actionable error instead of rebuilding the GPU runtime. If your pip policy
requires a virtual environment, use `-Mode System` with a compatible installed
Python or consult the person responsible for that policy; standalone portable
Python is not a venv, and the launcher does not silently disable this requirement.

After activating or relocating a managed environment, generated Python entry
points (including `pip.exe` and ROCm's `offload-arch.exe`) are checked and repaired
before accelerator validation. Only recognized package-owned wrappers and their
installation records are updated; native tools and the base system Python are
not rewritten. A successful check is remembered for that runtime path and helper
version, so a normal unchanged start does not rescan every installed file.
This is not a general-purpose environment packer: a system venv still needs its
base Python, and editable-package hooks can still refer to the original project
folder. Use `start_desktop.bat` and transfer user data with Power Switch rather
than assuming every installed console command is portable between computers.

Po polsku: launcher izoluje ścieżki i ustawienia startowe Pythona, ale zachowuje
zasady pip dotyczące sieci, certyfikatów i bezpieczeństwa. Ustawienia pip kierujące
instalację do innego katalogu lub Pythona powodują czytelny błąd, nie ponowną
instalację GPU. Jeśli pip wymaga venv, wybierz `-Mode System` ze zgodnym Pythonem
albo uzgodnij zmianę tej zasady; samodzielny Python portable nie jest venv.
Po zmianie lokalizacji środowiska launcher naprawia rozpoznane pliki uruchamiające
pakiety, w tym `pip.exe` i `offload-arch.exe`, przed testem GPU. Nie zmienia przy
tym systemowego Pythona. Wynik kontroli zapamiętuje, aby nie powtarzać pełnego
skanowania przy każdym starcie. To nie czyni dowolnego venv przenośnym między
komputerami: nadal potrzebuje on bazowego Pythona, a instalacja edytowalna może
odwoływać się do dawnego katalogu źródeł. Używaj `start_desktop.bat`; do przenoszenia
danych użytkownika służy Power Switch.

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
If a previous activation was interrupted between renames, the surviving `.old`
environment is retained for recovery rather than deleted. An unavailable or broken
system Python is treated as a repairable interpreter failure, not a fatal probe error.
Before modifying a runtime, OmniSonic checks whether another process is using
it and asks you to close that process. This also covers hidden desktop windows;
ordinary launches with an already valid runtime remain available.

A per-project lock prevents simultaneous launchers from modifying the same
runtime during preparation and startup. A second launcher reports that the
project is busy; it does not delete another launcher's staging environment.
The visible, foreground launcher retains this lock until the application exits.

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
launcher waits for the actual Python process to open an application window;
Windows virtual environments can first start a short-lived redirector process.
The GUI itself is not started with a hidden window style. Import errors, model
loading stages, and crashes are recorded in the ignored
`Workspace/launcher-logs/desktop-startup.log`. If the desktop quits before
opening or takes longer than three minutes, the launcher reports that path
instead of silently accepting the failed start. A failed hidden launch also
displays a standard Windows error dialog. The console stays available during
first-time installation and reappears if environment repair fails. Restart
OmniSonic after changing this option.

If loading the AI model reports only `[Errno 2] No such file or directory`, the
short message does not identify the missing file. After reproducing the problem,
include the latest `Traceback (most recent call last)` block through the final
exception from `Workspace/launcher-logs/desktop-startup.log`, plus **Copy
diagnostics**. That log is written for hidden launcher starts; a visible/direct
start may instead print the traceback in its console. Installation validation
checks the runtime, not every model file subsequently fetched through Hugging
Face. Do not delete presets, settings or the model cache based only on this
generic error. Logs can contain local paths; review the excerpt before sharing.

Jeśli ładowanie modelu kończy się samym `[Errno 2] No such file or directory`,
prześlij ostatni fragment od `Traceback (most recent call last)` do końca wyjątku
z `Workspace/launcher-logs/desktop-startup.log` oraz wynik **Kopiuj diagnostykę**.
Ten log powstaje przy uruchamianiu z ukrytą konsolą; przy starcie bezpośrednim lub
z widoczną konsolą pełny błąd może być wypisany tylko w niej. Sam komunikat nie
uzasadnia usuwania środowiska, presetów ani pobranych modeli. Przed udostępnieniem
sprawdź fragment logu — może zawierać lokalne ścieżki.

The **System** settings tab shows the active backend, device, PyTorch/TorchAudio
versions, model-loading library versions, CUDA/HIP/XPU state, Python, OS, and RAM. **Copy diagnostics** places a
report suitable for a bug submission on the clipboard.

Keyboard shortcuts can be edited on the **Keyboard shortcuts** settings tab.
Each command can be enabled independently, all shortcuts can be disabled with
one global checkbox, and the default assignments can be restored at any time.
`Ctrl+Shift+S` creates a preset from the reference audio currently loaded on
the **Voice Clone** tab and asks for its name.

In the settings dialog, Enter activates **Save** and Escape cancels. Escape
closes immediately when nothing changed and asks before discarding unsaved
changes otherwise.
The **Appearance** tab previews the light and dark palettes immediately. The
chosen theme also colours the app's own settings, preset, shortcut and progress
windows. Native Windows file pickers and system message boxes continue to use
the operating system's appearance.
Changing preset display labels applies immediately and keeps the selected
cloning preset. Refreshing the list or adding another preset no longer resets
that selection; removing the selected preset returns to the new-audio option.

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

**Preserve input folder structure** keeps each selected folder's name
and its subfolders inside the batch output, for example:
`Book/Chapter 1/part.txt` becomes `batch-.../Book/Chapter 1/part.wav`.
With multiple selected folders, each gets its own output tree. Individually
added files go directly into the batch directory. Duplicate folder or WAV names
get a numeric suffix instead of overwriting or merging unrelated inputs. If
selections overlap, a file is queued once using its first selection's origin.
Only folders containing queued text files are recreated; empty folders and
unrelated files are not copied. **Include subfolders** controls scanning, while
this new checkbox controls output layout and can be changed after scanning.
Both options are on by default. Disabling **Preserve input folder structure**
restores the flat, numbered output layout without excluding subfolder inputs.

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
with all saved voices. Settings are stored in `config/settings.json` next to
the program; temporary reference recordings use `config/temp/`. On the first
start after updating, existing user-profile settings (or the old root-level
`settings.json`) are copied once if the new file does not exist. The original
is retained; subsequent reads and writes use the portable configuration only.
The entire `config/` directory is ignored by Git. No other preset location is
scanned or migrated. The program folder must be writable.
Launcher Python/backend preferences also live in `config/`; Power Switch does
not transfer those hardware-specific preferences to another PC.

**Automatically transcribe reference audio files** is disabled by default in
Settings. Enable it if selecting/pasting a new reference path or completing a
microphone recording should start Whisper automatically. The previous transcript
is cleared when the reference changes. You can instead use **Transcribe**
manually. This checkbox only controls proactive transcription on file selection;
the engine still needs a transcript when creating a voice prompt and obtains one
if you generate/save a preset with an empty reference-text field.
Existing saved checkbox choices are not changed by updates.
**Preload ASR** is a separate option and is disabled by default. When disabled,
Whisper loads on first use, not together with the synthesis model. Changing this
setting takes effect after reloading the model; it does not by itself unload an
already loaded Whisper.

Settings / System also has two independent, **default-off** memory options:

- **Release the Whisper model from memory after transcription** unloads Whisper
  immediately after recognition, including recognition during cloning/preset
  creation. The next transcription reloads it on the selected accelerator.
- **Release the OmniVoice model from memory after each operation** unloads the
  synthesis model after generation, preset creation or another operation using
  it. A batch keeps the model for the entire queue and releases it when the queue
  finishes or is cancelled. The next operation loads it automatically.

These options drop model weights from RAM/VRAM, rather than move them to CPU.
Downloaded files stay on disk and generated audio remains playable/saveable.
Errors and cancellation also trigger cleanup. Changes apply to the next
operation, without restarting. Reloading models adds latency. If only OmniVoice
release is enabled, Whisper can remain cached independently; transcribing while
OmniVoice is unloaded loads only Whisper. Manual model unloading releases both.
With both options off, the existing keep-models-loaded behavior is unchanged.
GPU runtime/BLAS workspaces can still occupy a small amount of memory after all
model weights are released; zero VRAM usage is not expected while the app runs.

Whisper handles audio longer than 30 seconds using timestamp-enabled long-form
generation, but only plain text is inserted into the reference field. It uses
the same PyTorch accelerator as synthesis, including AMD ROCm; whisper.cpp is
not a required dependency. For voice cloning, prefer a clean 3–10-second sample
(the engine warns about long prompts); a full transcript prevents trimming the
reference to avoid mismatching the audio and its text.

Voice presets contain derived voice tokens and may contain a reference
transcript. Treat them as private data. The complete `presets/` tree is ignored
by Git.

The **Voice Presets** tab is the only place where presets can be removed. Delete
shows the configured warning, while Shift+Delete removes the selected preset
without that warning. Editing can rename a preset, update its transcript, or
rebuild its voice data from a new source recording. The original audio path is
not embedded in a preset, so choosing a replacement file during editing is
optional.

Choosing replacement audio in the preset editor clears the previous transcript;
enter the new recording's text or leave it blank for Whisper. Clearing the
replacement path restores the original transcript for rename-only editing.

Generated and recorded WAV files default to
`Documents\OmniSonic\generated` and `Documents\OmniSonic\record`. Both folders
can be entered directly or selected with **Browse** in settings. The related
checkbox chooses between saving directly to that configured folder and asking
for a destination each time.

Microphone capture uses the device's native/default sample rate; the engine
resamples reference audio when needed. If recording or saving fails after samples
have been captured, they stay in memory: **Retry saving recording** (also Ctrl+R)
opens Save As. Cancelling or failing that retry keeps the samples. Closing the
program with an active or unsaved recording always asks before discarding it.
Recording and model operations cannot run simultaneously in the same window.
Each application session has its own temporary reference WAV, so another open
instance cannot overwrite or remove it. Temporary files from previous sessions
are not silently removed by the current one.

WAV files and presets are staged in unique temporary files beside their destination.
A failed or cancelled write does not replace an existing file. Automatic WAV
names are reserved before writing so separate application instances cannot pick
the same unused name. Manual Save As still opens if the configured output folder
is unavailable, allowing another location to be chosen.

Preset files are checked before inference, including token types, codebook count
and model vocabulary bounds. Invalid generated samples are rejected before audio
postprocessing can disguise NaN or infinite values as a successful recording.
Preset symbolic links and junctions are not accepted; copy the actual preset file
into the program's `presets` folder. Ordinary readable cloud placeholders are not
treated as links when scanning input folders. Partially failed preset deletion
refreshes both lists to reflect the files that remain.

### Text normalization

The optional **Normalize numbers in text** setting includes lightweight
`num2words` integer conversion, including Polish and English. Select an explicit
language in the voice tab; Auto is rejected for this option so Polish numbers
cannot accidentally be normalized using the engine's English heuristic. The
same check applies to every batch mode, without discarding previous audio.

The basic converter preserves decimals, dates, times, identifiers and inline
voice/pronunciation tags instead of reading their digit fragments as integers.
It is not a full grammar-aware normalizer. Unsupported languages and missing
dependencies produce an explicit error. Optional WeText normalization remains
available for English/Chinese when its native dependencies are installed;
the Windows launcher does not install that native stack automatically. With
normalization disabled, language selection and generation are unchanged.

CFG zero is accepted as the engine's no-guidance setting. Extreme generation
settings can produce poor or silent audio; silence-only results that become
empty during postprocessing are reported as errors, not saved as success.

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
after environment activation/renaming and starts both system-venv and portable
`pythonw.exe` in a controlled test. It leaves disposable diagnostics in `trash/`.
For a full standalone ROCm installation on a supported AMD device, run
`powershell -ExecutionPolicy Bypass -File tests/smoke_portable_amd.ps1`. It creates
an isolated Python and GPU runtime in `Workspace/amd-portable-validation/`,
without replacing the application's `venv/`, `config/`, or presets.

`tests/test_operation_dispatch.py` covers queued GUI completions, cancellation
dialogs and stale callbacks. `tests/test_demo_reference.py` covers web clone
options, error reporting, PCM clipping and long-reference Whisper calls without
loading model weights. These regressions also run in CI.

`tests/test_inference_validation.py` covers malformed presets and decoded audio;
`tests/test_playback.py` covers pause/resume timing independently of the system
clock. `tests/test_ui_preferences.py` covers shortcut capture and localized input
validation. Optional `python -m tests.smoke_frame_lifecycle` and
`python -m tests.smoke_dialog_lifecycle` exercise actual wx modal/timer lifecycles
without loading a model or altering user settings.

`powershell -NoProfile -ExecutionPolicy Bypass -File tests/smoke_runtime_in_use.ps1`
optionally verifies protection against replacing an environment whose Python is
actually running. It starts short-lived hidden helpers and does not modify the
machine execution policy or replace the environments.

`python -B -m tests.smoke_normalization_ui` verifies real wx controls, Polish and
English messages, explicit-language checks, conversion and batch WAV writing
using synthetic synthesis. It requires the runtime dependencies but no model.
For cached-model synthesis plus normalization, zero-CFG raw decoding, disabled
chunking and two-reference pairing on a real device, use:

```powershell
python -B -m tests.smoke_inference --backend rocm --output Workspace/input-smoke --regression-inputs
```

Choose a new output directory for each test.

Optional real-device web regression (use a reference longer than 30 seconds):

```powershell
venv\Scripts\python -B tests/smoke_web_inference.py --backend rocm --reference long-test.wav --output trash/web-smoke
```

This uses locally cached models, checks the web UI's registered clone/design
callbacks and shared generation queue, and writes only diagnostic output. Choose
a new output directory for each run. Use `tests/smoke_model_memory.py` with the
same arguments to verify repeated model release/reload on the selected hardware.

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
