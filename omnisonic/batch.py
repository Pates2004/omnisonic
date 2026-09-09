"""Text-file discovery and sequential, cancellable synthesis without GUI dependencies."""

from __future__ import annotations

import codecs
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from .operations import OperationCancelled, OperationState


TEXT_EXTENSIONS = {".txt", ".md"}
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_BATCH_FILES = 5000


class BatchInputError(ValueError):
    """An input error represented by a translatable message key."""


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def discover_text_files(
    inputs: Iterable[str | Path],
    existing: Iterable[str | Path] = (),
    recursive: bool = True,
    check_cancelled: Callable[[], None] = lambda: None,
) -> tuple[list[Path], list[tuple[str, str]]]:
    found: list[Path] = []
    errors: list[tuple[str, str]] = []
    seen = {os.path.normcase(str(Path(path).resolve())) for path in existing}
    visited: set[str] = set()

    def visit(path: Path, explicit: bool):
        check_cancelled()
        try:
            if _is_link(path):
                if explicit:
                    errors.append((str(path), "batch_link_skipped"))
                return
            path = path.resolve()
            key = os.path.normcase(str(path))
            if path.is_dir():
                if key in visited:
                    return
                visited.add(key)
                for child in sorted(path.iterdir(), key=lambda item: item.name.casefold()):
                    if child.is_dir() and not recursive:
                        continue
                    visit(child, False)
            elif path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS:
                if key not in seen:
                    if len(seen) >= MAX_BATCH_FILES:
                        raise BatchInputError("batch_limit")
                    seen.add(key)
                    found.append(path)
            elif explicit:
                errors.append((str(path), "batch_unsupported"))
        except OSError as exc:
            errors.append((str(path), str(exc)))

    for candidate in inputs:
        visit(Path(candidate).expanduser(), True)
    return found, errors


def read_text_input(path: Path) -> str:
    with path.open("rb") as stream:
        data = stream.read(MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES:
        raise BatchInputError("batch_too_large")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    else:
        encoding = "utf-8-sig"
    try:
        text = data.decode(encoding).strip()
    except UnicodeError as exc:
        raise BatchInputError("batch_encoding_error") from exc
    if not text:
        raise BatchInputError("batch_empty_file")
    if "\0" in text:
        raise BatchInputError("batch_encoding_error")
    return text


@dataclass
class BatchResult:
    source: str
    status: str = "queued"
    output: str = ""
    error: str = ""


def process_text_batch(
    paths: list[Path],
    output_directory: Path,
    state: OperationState,
    synthesize: Callable,
    save_audio: Callable,
    on_result: Callable[[int, BatchResult], None] = lambda _index, _result: None,
) -> list[BatchResult]:
    """One file per model call; never overwrite an existing batch directory."""
    state.check_cancelled()
    output_directory.mkdir(parents=True, exist_ok=False)
    results = [BatchResult(str(path)) for path in paths]
    try:
        for index, path in enumerate(paths):
            state.check_cancelled()
            result = results[index]
            result.status = "running"
            on_result(index, BatchResult(**asdict(result)))
            stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", path.stem).strip(". ")[:100] or "audio"
            destination = output_directory / f"{index + 1:04d}_{stem}.wav"
            temporary = destination.with_suffix(".part.wav")
            try:
                text = read_text_input(path)
                audio = synthesize(text)
                state.check_cancelled()
                save_audio(temporary, audio)
                state.check_cancelled()
                temporary.replace(destination)
                result.status = "done"
                result.output = str(destination)
            except OperationCancelled:
                result.status = "cancelled"
                raise
            except Exception as exc:
                result.status = "failed"
                result.error = str(exc)
            finally:
                temporary.unlink(missing_ok=True)
                on_result(index, BatchResult(**asdict(result)))
    finally:
        report = {"cancelled": state.cancel_flag, "files": [asdict(item) for item in results]}
        (output_directory / "batch_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return results
