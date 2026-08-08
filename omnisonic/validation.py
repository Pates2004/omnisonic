"""Validation helpers for user-controlled file names."""

from __future__ import annotations

import os
import re
from pathlib import Path

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def validate_filename_component(value: str, *, label: str = "name") -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label} cannot be empty")
    if value in {".", ".."} or _INVALID_FILENAME_CHARS.search(value):
        raise ValueError(f"{label} contains characters that are not allowed in file names")
    if value.endswith((".", " ")):
        raise ValueError(f"{label} cannot end with a dot or space")
    if len(value) > 80:
        raise ValueError(f"{label} is too long (maximum: 80 characters)")
    base = value.split(".", 1)[0].upper()
    if base in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} is a reserved system name")
    return value


def preset_filename(name: str) -> str:
    name = name.strip()
    if name.lower().endswith(".pt"):
        name = name[:-3]
    return validate_filename_component(name, label="preset name") + ".pt"


def safe_child_path(directory: Path | str, filename: str) -> Path:
    directory = Path(directory).resolve()
    candidate = (directory / filename).resolve()
    try:
        common = os.path.commonpath((str(directory), str(candidate)))
    except ValueError as exc:
        raise ValueError("file must stay inside the selected directory") from exc
    if common != str(directory):
        raise ValueError("file must stay inside the selected directory")
    return candidate
