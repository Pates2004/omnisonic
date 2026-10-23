"""Print or verify the source-only updater manifest without changing any files."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Iterable

try:
    import tomllib
except ModuleNotFoundError:  # Python3.10 supports the project's simple static metadata.
    tomllib = None


MANIFEST_NAME = "update_manifest.json"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_FILES = 2048
_UNSAFE_CHARACTERS = re.compile(r'[\x00-\x1f\x7f:<>"|?*\\]')
_RESERVED_NAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])(?:\.|$)", re.I
)
_LOCAL_INSTRUCTIONS = re.compile(r"^AGENTS(?:\.override)?\.md$", re.I)
_PROTECTED_ROOT = re.compile(
    r"^(?:\.git|\.launcher|config|presets|Workspace|Forme|Trash|Snapshots|Installfiles|"
    r"omnivoice-local-launcher|power-switch-backups|\.venv|\.cache.*|env(?:[.-].*)?|"
    r"venv(?:[.-].*)?|settings\.json|start\.bat|\.gitmodules)$",
    re.I,
)
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}\Z", re.ASCII)


class ManifestError(ValueError):
    """The checkout cannot safely produce the updater's source manifest."""


def validate_relative_path(path: str) -> str:
    """Validate updater-safe, forward-slash paths independently of the host OS."""
    if (
        not isinstance(path, str)
        or not path
        or len(path) > 240
        or path.startswith("/")
        or _UNSAFE_CHARACTERS.search(path)
    ):
        raise ManifestError(f"Unsafe update path: {path!r}")
    for part in path.split("/"):
        if not part or part in {".", ".."} or part.endswith((".", " ")):
            raise ManifestError(f"Unsafe update path: {path!r}")
        if _RESERVED_NAME.match(part):
            raise ManifestError(f"Reserved Windows update path: {path!r}")
    return path


def is_protected_path(path: str) -> bool:
    parts = path.split("/")
    return (
        path.casefold() == MANIFEST_NAME
        or bool(_PROTECTED_ROOT.fullmatch(parts[0]))
        or any(part.casefold() == ".git" for part in parts)
        or any(_LOCAL_INSTRUCTIONS.fullmatch(part) for part in parts)
    )


def assert_no_links(path: Path) -> None:
    """Check every existing ancestor before resolving or reading the target."""
    for candidate in (path, *path.parents):
        metadata = candidate.lstat()
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ManifestError(f"Update paths cannot contain links/reparse points: {candidate}")


def source_bytes(path: Path) -> bytes:
    assert_no_links(path)
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FILE_BYTES:
        raise ManifestError(f"Invalid or oversized source file: {path}")
    content = path.read_bytes()
    if len(content) > MAX_FILE_BYTES:
        raise ManifestError(f"Oversized source file: {path}")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ManifestError(f"Source files must be UTF-8 text: {path}") from exc
    if b"\x00" in content:
        raise ManifestError(f"Binary source payload refused: {path}")
    return content.replace(b"\r\n", b"\n")


def _git(project: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(project), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise ManifestError("Git source discovery exceeded 30 seconds.") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ManifestError(f"Git source discovery failed: {detail}")
    return result.stdout


def project_root(project: Path) -> Path:
    candidate = Path(os.path.abspath(project))
    assert_no_links(candidate)
    reported = Path(_git(candidate, "rev-parse", "--show-toplevel").decode("utf-8").strip())
    if not candidate.samefile(reported):
        raise ManifestError("--project must name the actual Git root, not a subdirectory.")
    return candidate


def _version(project: Path) -> str:
    tree = ast.parse(source_bytes(project / "omnisonic/__init__.py").decode("utf-8-sig"))
    stores = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "__version__"
        and isinstance(node.ctx, ast.Store)
    ]
    assignments = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    if len(stores) != 1 or len(assignments) != 1:
        raise ManifestError("omnisonic.__version__ must be one static string assignment.")
    value = assignments[0].value
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        raise ManifestError("omnisonic.__version__ must be a static string, not executable code.")
    version = value.value
    if not _VERSION.fullmatch(version):
        raise ManifestError("Unsupported OmniSonic version string.")

    metadata = source_bytes(project / "pyproject.toml").decode("utf-8-sig")
    if tomllib is not None:
        try:
            declared = tomllib.loads(metadata).get("project", {}).get("version")
        except (ValueError, AttributeError) as exc:
            raise ManifestError("Invalid pyproject static project metadata.") from exc
        if declared != version:
            raise ManifestError("pyproject project.version and omnisonic.__version__ must match.")
        return version

    # Python3.10 has no standard TOML parser. Support the project's plain static
    # table, but fail closed on multiline strings that could contain fake tables.
    if '"""' in metadata or "'''" in metadata:
        raise ManifestError("Multiline pyproject metadata requires Python3.11 or newer.")
    section = None
    versions = []
    project_sections = 0
    for line in metadata.splitlines():
        if line.lstrip().startswith("["):
            table = re.fullmatch(r"\s*\[([^\[\]]+)\]\s*(?:#.*)?", line)
            section = table.group(1).strip() if table else None
            project_sections += section == "project"
        elif section == "project" and re.match(r"\s*version\s*=", line):
            entry = re.fullmatch(
                r"\s*version\s*=\s*(['\"])([A-Za-z0-9][A-Za-z0-9._+-]{0,79})\1\s*(?:#.*)?",
                line,
            )
            if entry is None:
                raise ManifestError("pyproject project.version must be a static version string.")
            versions.append(entry.group(2))
    if project_sections != 1 or versions != [version]:
        raise ManifestError("pyproject project.version and omnisonic.__version__ must match.")
    return version


def _source_paths(tracked: Iterable[str], include_new: Iterable[str]) -> list[str]:
    paths = []
    for path in tracked:
        validate_relative_path(path)
        if not is_protected_path(path):
            paths.append(path)
    for path in include_new:
        validate_relative_path(path)
        if is_protected_path(path):
            raise ManifestError(f"Explicit source path is protected: {path!r}")
        paths.append(path)
    seen = set()
    for path in paths:
        folded = path.casefold()
        if folded in seen:
            raise ManifestError(f"Duplicate case-insensitive source path: {path!r}")
        seen.add(folded)
    for path in paths:
        parts = path.casefold().split("/")
        if any("/".join(parts[:index]) in seen for index in range(1, len(parts))):
            raise ManifestError(f"Conflicting source file/directory path: {path!r}")
    if "start_desktop.bat" not in seen or not 1 <= len(paths) <= MAX_FILES:
        raise ManifestError("Manifest requires start_desktop.bat and at most 2048 source files.")
    return sorted(paths, key=lambda path: (path.casefold(), path))


def generate_manifest(project: Path, include_new: Iterable[str] = ()) -> dict:
    project = project_root(project)
    raw_paths = _git(project, "ls-files", "--cached", "-z")
    if raw_paths and not raw_paths.endswith(b"\0"):
        raise ManifestError("Git returned an incomplete NUL-delimited source list.")
    tracked = raw_paths.decode("utf-8").split("\0")[:-1] if raw_paths else []
    paths = _source_paths(tracked, include_new)
    manifest = {
        "schema": 1,
        "algorithm": "sha256-lf",
        "version": _version(project),
        "files": [
            {"path": path, "sha256": hashlib.sha256(source_bytes(project / path)).hexdigest()}
            for path in paths
        ],
    }
    if len(manifest_json(manifest).encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise ManifestError("Update manifest exceeds 1 MiB.")
    return manifest


def manifest_json(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=True, indent=2, allow_nan=False) + "\n"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"Duplicate manifest JSON key: {key!r}")
        result[key] = value
    return result


def check_manifest(project: Path, expected: dict) -> None:
    path = project / MANIFEST_NAME
    assert_no_links(path)
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ManifestError("Update manifest exceeds 1 MiB.")
    actual = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if json.dumps(actual, sort_keys=True, allow_nan=False) != json.dumps(
        expected, sort_keys=True, allow_nan=False
    ):
        raise ManifestError(
            "Source manifest is stale. Regenerate it after reviewing source changes."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(os.path.abspath(__file__)).parents[1])
    parser.add_argument("--include-new", action="append", default=[], metavar="RELATIVE_PATH")
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        project = project_root(arguments.project)
        manifest = generate_manifest(project, arguments.include_new)
        if arguments.check:
            check_manifest(project, manifest)
        else:
            sys.stdout.write(manifest_json(manifest))
        return 0
    except (ValueError, OSError, UnicodeError, SyntaxError) as exc:
        print(f"Source manifest error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
