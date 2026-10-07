"""Validation and localized error helpers for desktop input."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_REPARSE_TAG_NAME_SURROGATE = 0x20000000
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
    *(f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "\u00b9\u00b2\u00b3"),
}


class FilenameValidationError(ValueError):
    def __init__(self, message: str, message_key: str):
        super().__init__(message)
        self.message_key = message_key


def validation_error_message(error: Exception, translate_func) -> str:
    if isinstance(error, FilenameValidationError):
        return translate_func(error.message_key)
    return str(error)


def operation_error_message(error: Exception, translate_func) -> str:
    """Translate known engine errors without importing the inference runtime."""
    key = getattr(error, "message_key", None)
    if key in {
        "normalization_missing_dependency",
        "normalization_unsupported_language",
        "normalization_failed",
    }:
        return translate_func(key).format(language=getattr(error, "language", ""))
    return validation_error_message(error, translate_func)


def validate_filename_component(value: str, *, label: str = "name") -> str:
    value = value.strip()
    if not value:
        raise FilenameValidationError(f"{label} cannot be empty", "filename_empty")
    if value in {".", ".."} or _INVALID_FILENAME_CHARS.search(value):
        raise FilenameValidationError(
            f"{label} contains characters that are not allowed in file names",
            "filename_invalid_characters",
        )
    if value.endswith((".", " ")):
        raise FilenameValidationError(
            f"{label} cannot end with a dot or space", "filename_invalid_ending"
        )
    if len(value) > 80:
        raise FilenameValidationError(
            f"{label} is too long (maximum: 80 characters)", "filename_too_long"
        )
    base = value.split(".", 1)[0].upper()
    if base in _WINDOWS_RESERVED_NAMES:
        raise FilenameValidationError(f"{label} is a reserved system name", "filename_reserved")
    return value


def preset_filename(name: str) -> str:
    name = name.strip()
    if name.lower().endswith(".pt"):
        name = name[:-3]
    return validate_filename_component(name, label="preset name") + ".pt"


def is_path_link(path: Path | str) -> bool:
    """Detect redirects without rejecting ordinary cloud-backed reparse files."""
    info = Path(path).lstat()
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    if not attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        return False
    reparse_tag = getattr(info, "st_reparse_tag", 0)
    return not reparse_tag or bool(reparse_tag & _REPARSE_TAG_NAME_SURROGATE)


def safe_child_path(directory: Path | str, filename: str, *, reject_links: bool = False) -> Path:
    directory = Path(directory).resolve()
    candidate = directory / filename
    if reject_links:
        try:
            linked = is_path_link(candidate)
        except FileNotFoundError:
            linked = False
        if linked:
            raise FilenameValidationError(
                "symbolic link presets are not supported", "preset_link_not_allowed"
            )
    candidate = candidate.resolve()
    try:
        common = os.path.commonpath((str(directory), str(candidate)))
    except ValueError as exc:
        raise FilenameValidationError(
            "file must stay inside the selected directory", "filename_outside_directory"
        ) from exc
    if common != str(directory):
        raise FilenameValidationError(
            "file must stay inside the selected directory", "filename_outside_directory"
        )
    return candidate
