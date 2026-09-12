"""Configuration and user-data paths for the OmniSonic desktop app."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .shortcuts import (
    SHORTCUT_DEFINITIONS,
    default_shortcut_bindings,
    default_shortcut_enabled,
    normalize_shortcut,
)

logger = logging.getLogger(__name__)

APP_NAME = "OmniSonic"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = Path(__file__).resolve().parent


def _legacy_profile_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME.lower()


def _program_dir() -> Path:
    override = os.environ.get("OMNISONIC_APP_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    if (PROJECT_ROOT / "start_desktop.bat").is_file() or (
        PROJECT_ROOT / "pyproject.toml"
    ).is_file():
        return PROJECT_ROOT
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return Path(sys.prefix).resolve().parent
    return Path.cwd().resolve()


PROGRAM_DIR = _program_dir()
APP_DATA_DIR = PROGRAM_DIR / "config"
CONFIG_FILE = APP_DATA_DIR / "settings.json"
PRESETS_DIR = PROGRAM_DIR / "presets"
TEMP_DIR = APP_DATA_DIR / "temp"
RECORDED_AUDIO_FILE = TEMP_DIR / "recorded_reference.wav"


def default_audio_directory(kind: str) -> Path:
    documents = Path.home() / "Documents"
    if os.name == "nt":
        # Documents can be redirected to OneDrive or another disk by Windows.
        import ctypes

        try:
            buffer = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:
                if buffer.value:
                    documents = Path(buffer.value)
        except (AttributeError, OSError):
            pass
    if os.name == "nt" or documents.exists():
        return documents / APP_NAME / kind
    return APP_DATA_DIR / "audio" / kind


DEFAULT_CONFIG: dict[str, Any] = {
    "language": "en",
    "theme": "light",
    "hide_console": True,
    "force_splash": False,
    "show_progress": True,
    "use_native_dialogs": False,
    "first_run_done": False,
    "font_size": 10,
    "warn_exit": True,
    "remember_ai_settings": True,
    "clean_temp": True,
    "confirm_success": False,
    "ai_steps": 32,
    "ai_cfg": 2.0,
    "ai_speed": 1.0,
    "ai_denoise": True,
    "ai_t_shift": 0.1,
    "ai_layer_penalty_factor": 5.0,
    "ai_position_temperature": 5.0,
    "ai_class_temperature": 0.0,
    "ai_preprocess_prompt": True,
    "ai_postprocess_output": True,
    "ai_audio_chunk_duration": 15.0,
    "ai_audio_chunk_threshold": 30.0,
    "ai_pad_duration": 0.1,
    "ai_fade_duration": 0.1,
    "fake_progress_numbers": False,
    "preset_display_mode": "name",
    "asr_model_name": "openai/whisper-large-v3-turbo",
    "preload_asr": False,
    "auto_transcribe_reference": True,
    "unload_asr_after_transcription": False,
    "unload_omnivoice_after_operation": False,
    "normalize_text": False,
    "use_duration": False,
    "duration_val": 5.0,
    "clone_lang": "Auto",
    "clone_instruct": "",
    "design_lang": "Auto",
    "design_instruct": "",
    "auto_lang": "Auto",
    "warn_delete_preset": True,
    "auto_save_gen": False,
    "auto_save_gen_folder": False,
    "generated_audio_directory": str(default_audio_directory("generated")),
    "prefix_gen": "generated",
    "auto_save_rec": False,
    "auto_save_rec_folder": False,
    "recorded_audio_directory": str(default_audio_directory("record")),
    "prefix_rec": "record",
    "shortcuts_enabled": True,
    "shortcut_bindings": default_shortcut_bindings(),
    "shortcut_enabled": default_shortcut_enabled(),
}


def _clamp_number(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default


def normalize_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge persisted values with defaults and validate important fields."""
    result = deepcopy(DEFAULT_CONFIG)
    if config:
        result.update({key: deepcopy(config[key]) for key in DEFAULT_CONFIG if key in config})
        if "hide_console" not in config and isinstance(config.get("show_console"), bool):
            result["hide_console"] = not config["show_console"]

    for key, default in DEFAULT_CONFIG.items():
        if isinstance(default, bool) and not isinstance(result.get(key), bool):
            result[key] = default

    result["font_size"] = int(_clamp_number(result.get("font_size"), 10, 8, 24))
    result["ai_steps"] = int(_clamp_number(result.get("ai_steps"), 32, 1, 100))
    result["ai_cfg"] = _clamp_number(result.get("ai_cfg"), 2.0, 0.1, 10.0)
    result["ai_speed"] = _clamp_number(result.get("ai_speed"), 1.0, 0.1, 5.0)
    result["ai_t_shift"] = _clamp_number(result.get("ai_t_shift"), 0.1, 0.001, 10.0)
    result["ai_layer_penalty_factor"] = _clamp_number(
        result.get("ai_layer_penalty_factor"), 5.0, 0.0, 100.0
    )
    result["ai_position_temperature"] = _clamp_number(
        result.get("ai_position_temperature"), 5.0, 0.0, 100.0
    )
    result["ai_class_temperature"] = _clamp_number(
        result.get("ai_class_temperature"), 0.0, 0.0, 100.0
    )
    result["ai_audio_chunk_duration"] = _clamp_number(
        result.get("ai_audio_chunk_duration"), 15.0, 0.0, 3600.0
    )
    result["ai_audio_chunk_threshold"] = _clamp_number(
        result.get("ai_audio_chunk_threshold"), 30.0, 0.0, 3600.0
    )
    result["ai_pad_duration"] = _clamp_number(result.get("ai_pad_duration"), 0.1, 0.0, 10.0)
    result["ai_fade_duration"] = _clamp_number(result.get("ai_fade_duration"), 0.1, 0.0, 10.0)
    result["duration_val"] = _clamp_number(result.get("duration_val"), 5.0, 0.1, 100.0)

    if result.get("theme") not in {"light", "dark"}:
        result["theme"] = "light"
    if result.get("preset_display_mode") not in {"name", "path", "name_path"}:
        result["preset_display_mode"] = "name"
    for key in (
        "language",
        "asr_model_name",
        "prefix_gen",
        "prefix_rec",
        "generated_audio_directory",
        "recorded_audio_directory",
    ):
        if not isinstance(result.get(key), str) or not result[key].strip():
            result[key] = DEFAULT_CONFIG[key]
        else:
            result[key] = result[key].strip()
    for key in ("clone_instruct", "design_instruct"):
        if not isinstance(result.get(key), str):
            result[key] = ""

    raw_bindings = result.get("shortcut_bindings")
    if not isinstance(raw_bindings, Mapping):
        raw_bindings = {}
    raw_enabled = result.get("shortcut_enabled")
    if not isinstance(raw_enabled, Mapping):
        raw_enabled = {}
    bindings: dict[str, str] = {}
    enabled: dict[str, bool] = {}
    for definition in SHORTCUT_DEFINITIONS:
        try:
            bindings[definition.key] = normalize_shortcut(
                raw_bindings.get(definition.key, definition.default)
            )
        except ValueError:
            bindings[definition.key] = definition.default
        shortcut_enabled = raw_enabled.get(definition.key, True)
        enabled[definition.key] = shortcut_enabled if isinstance(shortcut_enabled, bool) else True
    result["shortcut_bindings"] = bindings
    result["shortcut_enabled"] = enabled
    return result


def load_config(path: Path | str = CONFIG_FILE) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("configuration root must be a JSON object")
        return normalize_config(data)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Could not load configuration from %s: %s", path, exc)
        return deepcopy(DEFAULT_CONFIG)


def save_config(config: Mapping[str, Any], path: Path | str = CONFIG_FILE) -> None:
    """Persist configuration atomically so interruption cannot corrupt it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(normalize_config(config), ensure_ascii=False, indent=4) + "\n"
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_name = temp_file.name
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except OSError:
                logger.warning("Could not remove temporary config file %s", temp_name)


def ensure_user_directories() -> None:
    for directory in (APP_DATA_DIR, PRESETS_DIR, TEMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def migrate_legacy_user_data() -> None:
    """One-time settings copy into program/config; never remove the original."""
    ensure_user_directories()
    if CONFIG_FILE.exists():
        return
    # A relocated/test application must not import the real user's settings.
    candidates = [PROGRAM_DIR / "settings.json"]
    if PROGRAM_DIR == PROJECT_ROOT:
        candidates.insert(0, _legacy_profile_dir() / "settings.json")
    for source in candidates:
        if not source.is_file():
            continue
        try:
            data = json.loads(source.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("configuration root must be a JSON object")
        except (OSError, UnicodeError, ValueError) as exc:
            logger.warning("Could not read old settings %s: %s", source, exc)
            continue
        save_config(data, CONFIG_FILE)
        logger.info("Copied settings from %s to %s; original retained", source, CONFIG_FILE)
        break


def locale_search_directories() -> tuple[Path, ...]:
    """Return packaged and source-checkout locale locations."""
    return (PACKAGE_DIR / "langs", PROJECT_ROOT / "langs")
