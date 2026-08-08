"""Locale loading with deterministic fallback and diagnostics."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

FALLBACK_ENGLISH = {
    "title": "OmniSonic",
    "msg_error": "Error: ",
    "btn_save": "Save",
    "btn_cancel": "Cancel",
    "first_run_title": "Setup",
    "lang_lbl": "Language",
    "theme_lbl": "Theme",
    "font_size_lbl": "Font size",
    "warning_title": "Warning",
    "error_title": "Error",
    "success_title": "Success",
    "info_title": "Information",
    "startup_title": "Starting OmniSonic",
    "startup_msg": "Loading AI libraries...",
    "msg_wait": "Please wait...",
    "cancel_pending": "Cancellation requested. Waiting for the current model call to finish...",
}


def load_locales(search_directories: Iterable[Path]) -> dict[str, dict[str, str]]:
    locales: dict[str, dict[str, str]] = {}
    seen: set[Path] = set()
    for directory in search_directories:
        directory = Path(directory)
        if directory in seen or not directory.is_dir():
            continue
        seen.add(directory)
        for locale_file in sorted(directory.glob("*.lng")):
            code = locale_file.stem
            if code in locales:
                continue
            try:
                data = json.loads(locale_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not all(
                    isinstance(key, str) and isinstance(value, str) for key, value in data.items()
                ):
                    raise ValueError("locale must contain string keys and values")
                locales[code] = data
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Could not load locale %s: %s", locale_file, exc)

    if "en" not in locales:
        locales["en"] = FALLBACK_ENGLISH.copy()
    else:
        for key, value in FALLBACK_ENGLISH.items():
            locales["en"].setdefault(key, value)
    return locales


def translate(locales: dict[str, dict[str, str]], language: str, key: str) -> str:
    selected = locales.get(language, locales.get("en", FALLBACK_ENGLISH))
    english = locales.get("en", FALLBACK_ENGLISH)
    return selected.get(key, english.get(key, key))


def missing_keys(
    locales: dict[str, dict[str, str]], reference_language: str = "en"
) -> dict[str, set[str]]:
    reference = set(locales.get(reference_language, {}))
    return {
        language: reference - set(values)
        for language, values in locales.items()
        if language != reference_language
    }
