"""Failure-safe file replacement and collision-free numbered output names."""

import logging
import os
import tempfile
from itertools import count
from pathlib import Path

from .validation import validate_filename_component

logger = logging.getLogger(__name__)


def atomic_write(path, writer, check_cancelled=lambda: None):
    """Write beside the target, then replace it only after a successful write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".omnisonic-", suffix=path.suffix, dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        check_cancelled()
        writer(temporary)
        check_cancelled()
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove partial file %s: %s", temporary, exc)


def _numbered_audio_paths(folder, prefix):
    yield folder / f"{prefix}.wav"
    for index in count(1):
        yield folder / f"{prefix}{index}.wav"


def suggest_audio_name(folder, prefix):
    prefix = validate_filename_component(prefix, label="audio prefix")
    for path in _numbered_audio_paths(Path(folder), prefix):
        if not os.path.lexists(path):
            return path.name


def _write_new_audio(path, writer):
    # Keep reservation failure separate from a FileExistsError in the writer.
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except PermissionError:
        # Windows can report EACCES for an occupied directory or read-only
        # entry. A failure to create a genuinely new file must still surface.
        if os.path.lexists(path):
            return False
        raise
    try:
        os.close(descriptor)
        atomic_write(path, writer)
    except BaseException:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove failed audio reservation %s: %s", path, exc)
        raise
    return True


def write_numbered_audio(folder, prefix, writer):
    """Reserve the first unused name before writing, including across instances."""
    folder = Path(folder)
    prefix = validate_filename_component(prefix, label="audio prefix")
    folder.mkdir(parents=True, exist_ok=True)
    for path in _numbered_audio_paths(folder, prefix):
        if _write_new_audio(path, writer):
            return path


def write_named_audio(path, writer, confirm_overwrite):
    """Preserve a manually chosen name; replace only after explicit confirmation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _write_new_audio(path, writer):
        return path
    if path.is_dir():
        raise IsADirectoryError(path)
    if confirm_overwrite(path):
        atomic_write(path, writer)
        return path
    return None
