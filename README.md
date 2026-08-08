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
- an NVIDIA GPU is recommended for practical generation speed;
- a working audio output device; microphone access is required only for recording.

The installer selects the CUDA build of PyTorch when an NVIDIA installation is
detected and otherwise installs the CPU build. CPU inference can be very slow.
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
system Python. It remembers the choice, installs wxPython and the audio/AI
dependencies, verifies them with `pip check` and runtime imports, and repairs a
damaged environment on the next launch. Installation failures are reported
instead of being ignored.

The mode can be changed explicitly with `start_desktop.bat -Mode Portable` or
`start_desktop.bat -Mode System`. `start_desktop.bat -InstallOnly` installs and
validates everything without opening the desktop application.

When **Hide launcher console** is enabled, normal launches are handed off to
`pythonw.exe` so the console does not remain open with the application. The
launcher keeps its console available during first-time installation and shows
it again if startup or environment repair fails. Restart OmniSonic after
changing this option so the launcher can select the correct Python executable.

Keyboard shortcuts can be edited on the **Keyboard shortcuts** settings tab.
Each command can be enabled independently, all shortcuts can be disabled with
one global checkbox, and the default assignments can be restored at any time.
`Ctrl+Shift+S` creates a preset from the reference audio currently loaded on
the **Voice Clone** tab and asks for its name.

Manual setup:

```powershell
python -m venv venv
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\python -m pip install -e ".[desktop]"
venv\Scripts\python -m omnisonic.app
```

After installation, the `omnisonic` command is also available.

## Dane prywatne / Private data

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

Generated and recorded WAV files are saved under
`Documents\OmniSonic\generated` and `Documents\OmniSonic\recorded`, unless the
user chooses another location.

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

## Project structure

- `omnisonic/` — desktop application, configuration, localization, and UI state;
- `omnivoice/` — bundled upstream TTS engine, training, evaluation, and CLI tools;
- `langs/` — Polish and English desktop translations;
- `tests/` — lightweight desktop tests and optional model integration tests;
- `start_desktop.bat` / `desktop_launcher.ps1` — verified Windows launcher,
  Python bootstrap, installer, and repair entry point.

## Credits and license

- OmniSonic desktop application: Pates2004;
- OmniVoice engine: Han Zhu and the
  [k2-fsa OmniVoice contributors](https://github.com/k2-fsa/OmniVoice).

Licensed under Apache-2.0. See [LICENSE](LICENSE).
