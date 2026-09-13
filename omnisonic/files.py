"""Failure-safe file replacement and collision-free numbered output names."""

import os
import tempfile
from pathlib import Path

from .validation import validate_filename_component


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
        temporary.unlink(missing_ok=True)


def write_numbered_audio(folder, prefix, writer):
    """Reserve an unused name before writing, including across app instances."""
    prefix = validate_filename_component(prefix, label="audio prefix")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        path = folder / f"{prefix}_{index}.wav"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            index += 1
            continue
        os.close(descriptor)
        try:
            atomic_write(path, writer)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path
