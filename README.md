# OmniSonic 🎧

OmniSonic is an advanced, fully-featured desktop Graphical User Interface (GUI) wrapper for the [OmniVoice](https://github.com/k2-fsa/OmniVoice) Text-to-Speech (TTS) model. Built with Python and wxPython, OmniSonic makes state-of-the-art zero-shot voice cloning and voice design accessible without touching the command line.

## Key Features

- **Intuitive Desktop GUI**: A native desktop application built with wxPython for seamless user experience.
- **Voice Cloning & Voice Design**: Easily clone voices from reference audio files or design voices using attributes like gender, pitch, age, and accent.
- **Microphone Recording**: Built-in microphone recording to instantly clone your own voice or any captured audio.
- **Advanced Audio Playback**: Smart audio player with Pause, Resume, and Stop capabilities for both reference audio and generated speech.
- **Preset System**: Save and load your favorite voice clone prompts and design configurations as presets for quick access.
- **Bilingual Interface**: Full support for both Polish (PL) and English (EN) out of the box, switchable on the fly.
- **Highly Configurable**: Control AI parameters (CFG, Speed, Steps, Denoising) and UI behavior (notifications, themes, font sizes, temp file cleanup) via an organized Settings tab.

## Installation

OmniSonic requires Python and a working installation of the `omnivoice` library.

1. **Install OmniVoice**:
   Follow the [official OmniVoice installation guide](https://github.com/k2-fsa/OmniVoice) to install PyTorch and the model.

2. **Install OmniSonic Requirements**:
   ```bash
   pip install wxpython sounddevice soundfile numpy plyer
   ```

3. **Run the App**:
   ```bash
   python wx_app.py
   ```

## Usage

### Voice Cloning (Klonowanie Głosu)
1. Navigate to the **Clone Voice** tab.
2. Select a reference audio file from your computer or record one using your microphone.
3. Type the text you want to generate.
4. Click **Generate** and listen to the cloned voice!

### Voice Design (Projektowanie Głosu)
1. Navigate to the **Voice Design** tab.
2. Type the text you want to generate.
3. Enter instructions for the AI (e.g., "female, low pitch, british accent").
4. Click **Generate**.

### Presets
Save your favorite prompts and voices in the **Presets** tab. You can name them and easily retrieve them later. You can configure how presets are displayed (Name only, Full path, or both) in the Settings.

### Settings
Click on **Settings** (Ustawienia) to customize your OmniSonic experience:
- **Appearance & Language**: Change language (PL/EN) and UI theme.
- **System & Presets**: Manage console visibility, preset display style, and temp file cleaning.
- **AI Options**: Configure generation notification popups and system alerts.

## Credits

- GUI & App logic: Pates2004 (OmniSonic)
- Underlying TTS AI Engine: [OmniVoice](https://github.com/k2-fsa/OmniVoice) by the k2-fsa team.
