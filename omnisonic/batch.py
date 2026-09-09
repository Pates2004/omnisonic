"""Text-file discovery and sequential, cancellable synthesis without GUI dependencies."""

from __future__ import annotations

import codecs
import json
import os
import re
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

from .operations import OperationCancelled, OperationState


TEXT_EXTENSIONS = {".txt", ".md"}
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_BATCH_FILES = 5000


class BatchInputError(ValueError):
    """An input error represented by a translatable message key."""


@dataclass(frozen=True)
class BatchInput:
    path: Path
    root: Path | None = None


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
) -> tuple[list[BatchInput], list[tuple[str, str]]]:
    """Keep the first selection's folder origin when input selections overlap."""
    found: list[BatchInput] = []
    errors: list[tuple[str, str]] = []
    seen = {os.path.normcase(str(Path(path).resolve())) for path in existing}
    visited: set[str] = set()

    def visit(path: Path, explicit: bool, root: Path | None = None):
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
                    visit(child, False, root if root is not None else path)
            elif path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS:
                if key not in seen:
                    if len(seen) >= MAX_BATCH_FILES:
                        raise BatchInputError("batch_limit")
                    seen.add(key)
                    found.append(BatchInput(path, root))
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
    source_root: str | None = None


def _output_name(name: str, fallback: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:200].rstrip(". ") or fallback
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", name, re.I):
        name = "_" + name
    return name


def plan_batch_outputs(inputs: list[BatchInput], preserve_structure: bool) -> list[Path]:
    """Allocate relative, Windows-safe names without merging unrelated input folders."""
    if not preserve_structure:
        return [
            Path(f"{index + 1:04d}_{_output_name(item.path.stem, 'audio')}.wav")
            for index, item in enumerate(inputs)
        ]

    # Reserve directories before files, including names such as a folder 'voice.wav'.
    used = {"batch_report.json"}
    directories: dict[tuple[str, ...], Path] = {}
    parents: list[Path] = []

    def reserve(parent: Path, name: str, extension: str = "") -> Path:
        candidate = parent / (name + extension)
        number = 1
        while candidate.as_posix().casefold() in used:
            number += 1
            candidate = parent / f"{name} ({number}){extension}"
        used.add(candidate.as_posix().casefold())
        return candidate

    for item in inputs:
        parent = Path()
        if item.root is not None:
            root = item.root.resolve()
            relative = item.path.resolve().relative_to(root)
            if not relative.name:
                raise ValueError("Batch source must be a file inside its input folder")
            source_key = (os.path.normcase(str(root)),)
            for index, name in enumerate((root.name or "folder", *relative.parts[:-1])):
                if index:
                    source_key += (os.path.normcase(name),)
                if source_key not in directories:
                    directories[source_key] = reserve(parent, _output_name(name, "folder"))
                parent = directories[source_key]
        parents.append(parent)

    return [
        reserve(parent, _output_name(item.path.stem, "audio"), ".wav")
        for item, parent in zip(inputs, parents, strict=True)
    ]


def process_text_batch(
    inputs: list[BatchInput],
    output_directory: Path,
    state: OperationState,
    synthesize: Callable,
    save_audio: Callable,
    on_result: Callable[[int, BatchResult], None] = lambda _index, _result: None,
    *,
    preserve_structure: bool = False,
) -> list[BatchResult]:
    """One file per model call; never overwrite an existing batch directory."""
    state.check_cancelled()
    relative_outputs = plan_batch_outputs(inputs, preserve_structure)
    output_directory.mkdir(parents=True, exist_ok=False)
    results = [
        BatchResult(str(item.path), source_root=str(item.root) if item.root is not None else None)
        for item in inputs
    ]
    try:
        for index, item in enumerate(inputs):
            state.check_cancelled()
            result = results[index]
            result.status = "running"
            on_result(index, BatchResult(**asdict(result)))
            destination = output_directory / relative_outputs[index]
            temporary = None
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                text = read_text_input(item.path)
                audio = synthesize(text)
                state.check_cancelled()
                # A source named 'voice.part.txt' must not collide with temporary audio.
                descriptor, name = tempfile.mkstemp(
                    prefix=".omnisonic-", suffix=".part.wav", dir=destination.parent
                )
                os.close(descriptor)
                temporary = Path(name)
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
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
                on_result(index, BatchResult(**asdict(result)))
    finally:
        report = {
            "cancelled": state.cancel_flag,
            "preserve_structure": preserve_structure,
            "files": [asdict(item) for item in results],
        }
        (output_directory / "batch_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return results
