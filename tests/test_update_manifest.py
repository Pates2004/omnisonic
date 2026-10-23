"""Source-manifest generation with isolated, owned Git fixtures only."""

import contextlib
import hashlib
import io
import json
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.materials import scratch_directory
from tools import update_manifest as updater


ROOT = Path(__file__).resolve().parents[1]


class UpdateManifestTests(unittest.TestCase):
    def setUp(self):
        self.project = scratch_directory("update-manifest-")
        self.git("init", "--quiet")
        self.write("omnisonic/__init__.py", '__version__ = "1.2.3"\n')
        self.write("pyproject.toml", '[project]\nname = "fixture"\nversion = "1.2.3"\n')
        self.write("start_desktop.bat", "@echo off\r\nexit /b 0\r\n")
        self.track("omnisonic/__init__.py", "pyproject.toml", "start_desktop.bat")

    def git(self, *arguments):
        return subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "-c",
                "core.safecrlf=false",
                "-C",
                str(self.project),
                *arguments,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout

    def write(self, relative, content):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    def track(self, *relative):
        self.git("add", "--force", "--", *relative)

    def generate(self, *include_new):
        return updater.generate_manifest(self.project, include_new)

    def save_manifest(self, manifest):
        self.write(updater.MANIFEST_NAME, updater.manifest_json(manifest))

    def test_deterministic_schema_order_and_hashes(self):
        self.write("z-source.py", "last\n")
        self.write("a-source.py", "first\n")
        self.track("z-source.py", "a-source.py")

        manifest = self.generate()

        self.assertEqual(manifest, self.generate())
        self.assertEqual(manifest["schema"], 1)
        self.assertEqual(manifest["algorithm"], "sha256-lf")
        self.assertEqual(manifest["version"], "1.2.3")
        paths = [item["path"] for item in manifest["files"]]
        self.assertEqual(paths, sorted(paths, key=lambda path: (path.casefold(), path)))
        self.assertTrue(all("\\" not in path for path in paths))
        entries = {item["path"]: item["sha256"] for item in manifest["files"]}
        self.assertEqual(entries["a-source.py"], hashlib.sha256(b"first\n").hexdigest())

    def test_unknown_files_require_explicit_exact_inclusion(self):
        self.write("reviewed.py", "approved\n")
        self.write("private-unreviewed.py", "not managed\n")
        baseline = {entry["path"] for entry in self.generate()["files"]}
        added = {entry["path"] for entry in self.generate("reviewed.py")["files"]}

        self.assertEqual(added - baseline, {"reviewed.py"})
        self.assertNotIn("private-unreviewed.py", added)
        with self.assertRaises(updater.ManifestError):
            self.generate("*.py")

    def test_manifest_and_local_instruction_files_are_never_managed(self):
        for path in ("update_manifest.json", "AGENTS.md", "docs/AGENTS.override.md"):
            self.write(path, "local only\n")
            self.track(path)

        paths = {entry["path"] for entry in self.generate()["files"]}

        self.assertNotIn("update_manifest.json", paths)
        self.assertNotIn("AGENTS.md", paths)
        self.assertNotIn("docs/AGENTS.override.md", paths)
        for path in ("update_manifest.json", "AGENTS.md", "docs/AGENTS.override.md"):
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(updater.ManifestError, "protected"),
            ):
                self.generate(path)

    def test_protected_tracked_directories_are_excluded(self):
        protected = (
            "config/settings.json",
            "presets/private.pt",
            "env/marker.txt",
            "env.retained-fixture/marker.txt",
            "venv.new/marker.txt",
            ".launcher/runtime.txt",
            ".venv/marker.txt",
            ".cache-fixture/marker.txt",
            "Workspace/log.txt",
            "Trash/sample.txt",
            "Forme/audit.txt",
            "Snapshots/old.txt",
            "Installfiles/package.txt",
            "omnivoice-local-launcher/launcher.ps1",
            "power-switch-backups/profile.txt",
            "settings.json",
            "start.bat",
            ".gitmodules",
        )
        for path in protected:
            self.write(path, "private synthetic fixture\n")
        self.track(*protected)

        paths = {entry["path"] for entry in self.generate()["files"]}

        self.assertTrue(paths.isdisjoint(protected))
        for path in protected:
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(updater.ManifestError, "protected"),
            ):
                self.generate(path)
        self.assertTrue(updater.is_protected_path("CONFIG/SETTINGS.JSON"))
        self.assertTrue(updater.is_protected_path("nested/agents.OVERRIDE.md"))
        self.assertTrue(updater.is_protected_path("nested/.GIT/config"))
        with self.assertRaisesRegex(updater.ManifestError, "protected"):
            self.generate("nested/.git/config")
        self.assertFalse(updater.is_protected_path("examples/config/training.json"))

    def test_check_detects_stale_sources_and_accepts_crlf_parity(self):
        source = self.write("source.py", b"first\r\nsecond\r\n")
        self.track("source.py")
        original = self.generate()
        self.save_manifest(original)

        source.write_bytes(b"first\nsecond\n")
        self.assertEqual(self.generate(), original)
        updater.check_manifest(self.project, self.generate())

        source.write_bytes(b"changed\nsecond\n")
        with self.assertRaisesRegex(updater.ManifestError, "stale"):
            updater.check_manifest(self.project, self.generate())

    def test_hashing_preserves_bom_lone_cr_and_final_newline(self):
        content = b"\xef\xbb\xbftext\r\nwith\rlone CR\n"
        path = self.write("text.py", content)

        normalized = updater.source_bytes(path)

        self.assertEqual(normalized, b"\xef\xbb\xbftext\nwith\rlone CR\n")
        self.assertEqual(path.read_bytes(), content)

    def test_casefold_duplicates_and_file_directory_conflicts_are_refused(self):
        with self.assertRaisesRegex(updater.ManifestError, "Duplicate"):
            self.generate("START_DESKTOP.BAT")
        with self.assertRaisesRegex(updater.ManifestError, "Duplicate"):
            self.generate("new.py", "new.py")
        with self.assertRaisesRegex(updater.ManifestError, "Conflicting"):
            updater._source_paths(["start_desktop.bat", "folder", "Folder/file.py"], [])

    def test_windows_unsafe_paths_are_rejected_before_filesystem_access(self):
        for path in (
            "",
            "../outside.py",
            "source/../outside.py",
            "/absolute.py",
            "C:/absolute.py",
            "source\\file.py",
            "file.py:stream",
            "double//separator.py",
            "trailing./file.py",
            "trailing /file.py",
            "CON.py",
            "nested/lpt1.txt",
            "nested/AUX",
            "nested/COM\u00b9.txt",
            "nested/LPT\u00b2.txt",
            "nested/COM\u00b3.txt",
            "bad\x00name.py",
            "bad\x7fname.py",
            "x" * 241,
        ):
            with self.subTest(path=path), self.assertRaises(updater.ManifestError):
                self.generate(path)

    def test_source_link_and_ancestor_reparse_are_rejected(self):
        source = self.project / "start_desktop.bat"
        original_lstat = Path.lstat

        def metadata(path, *args, **kwargs):
            if path == source:
                return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
            return original_lstat(path, *args, **kwargs)

        with (
            patch.object(Path, "lstat", metadata),
            self.assertRaisesRegex(updater.ManifestError, "links/reparse"),
        ):
            self.generate()

        def ancestor_metadata(path, *args, **kwargs):
            if path == self.project.parent:
                return SimpleNamespace(
                    st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT
                )
            return original_lstat(path, *args, **kwargs)

        with (
            patch.object(Path, "lstat", ancestor_metadata),
            self.assertRaisesRegex(updater.ManifestError, "links/reparse"),
        ):
            self.generate()

    def test_binary_or_non_utf8_source_is_not_silently_omitted(self):
        for content in (b"binary\x00payload", b"invalid\xffUTF8"):
            with self.subTest(content=content):
                self.write("source.py", content)
                self.track("source.py")
                with self.assertRaises(updater.ManifestError):
                    self.generate()

    def test_source_size_and_manifest_count_limits_are_enforced(self):
        with (
            patch.object(updater, "MAX_FILE_BYTES", 1),
            self.assertRaisesRegex(updater.ManifestError, "oversized"),
        ):
            self.generate()
        with (
            patch.object(updater, "MAX_FILES", 1),
            self.assertRaisesRegex(updater.ManifestError, "2048"),
        ):
            self.generate()
        with (
            patch.object(updater, "MAX_MANIFEST_BYTES", 1),
            self.assertRaisesRegex(updater.ManifestError, "1 MiB"),
        ):
            self.generate()

    def test_static_versions_must_match_without_executing_package_code(self):
        self.write(
            "omnisonic/__init__.py", 'raise RuntimeError("never import")\n__version__="1.2.3"\n'
        )
        self.assertEqual(self.generate()["version"], "1.2.3")
        self.write("pyproject.toml", '[project]\nversion = "1.2.4"\n')
        with self.assertRaisesRegex(updater.ManifestError, "must match"):
            self.generate()

    def test_dynamic_or_ambiguous_version_assignments_are_refused(self):
        for source in (
            '__version__ = str("1.2.3")\n',
            '__version__ = "1.2.3"\n__version__ = "1.2.3"\n',
            'if True:\n    __version__ = "1.2.3"\n',
        ):
            with self.subTest(source=source):
                self.write("omnisonic/__init__.py", source)
                with self.assertRaises(updater.ManifestError):
                    self.generate()

    def test_static_toml_version_stays_inside_project_section(self):
        for content in (
            '[project]\nname="fixture"\n[other]\nversion="1.2.3"\n',
            '[project]\nversion="1.2.3"\nversion="1.2.3"\n',
            '[project]\nversion="1.2.3"\n[project]\nname="fixture"\n',
        ):
            with self.subTest(content=content):
                self.write("pyproject.toml", content)
                with self.assertRaises(updater.ManifestError):
                    self.generate()
        self.write("pyproject.toml", "[project] # static\nversion = '1.2.3' # release\n")
        self.assertEqual(self.generate()["version"], "1.2.3")

    def test_toml_multiline_text_cannot_spoof_a_project_version(self):
        self.write("pyproject.toml", 'description = """\n[project]\nversion="1.2.3"\n"""\n')
        with self.assertRaises(updater.ManifestError):
            self.generate()
        with (
            patch.object(updater, "tomllib", None),
            self.assertRaisesRegex(updater.ManifestError, "Multiline"),
        ):
            self.generate()

    def test_python310_static_metadata_fallback_stays_fail_closed(self):
        with patch.object(updater, "tomllib", None):
            self.assertEqual(self.generate()["version"], "1.2.3")
            self.write("pyproject.toml", '[project]\nversion="1.2.3"\nversion="1.2.3"\n')
            with self.assertRaises(updater.ManifestError):
                self.generate()

    def test_missing_bootstrap_or_deleted_tracked_source_fails(self):
        with self.assertRaisesRegex(updater.ManifestError, "start_desktop.bat"):
            updater._source_paths(["source.py"], [])
        self.write("deleted.py", "temporary fixture\n")
        self.track("deleted.py")
        (self.project / "deleted.py").unlink()
        with self.assertRaises(OSError):
            self.generate()

    def test_cli_prints_json_only_and_check_never_rewrites_files(self):
        script = ROOT / "tools/update_manifest.py"
        source = self.project / "start_desktop.bat"
        original = source.read_bytes()
        command = [sys.executable, "-B", str(script), "--project", str(self.project)]
        generated = subprocess.run(command, capture_output=True, check=True)
        manifest = json.loads(generated.stdout)
        self.assertEqual(manifest, self.generate())
        self.assertFalse((self.project / updater.MANIFEST_NAME).exists())
        self.write(updater.MANIFEST_NAME, generated.stdout)
        before = (self.project / updater.MANIFEST_NAME).read_bytes()
        result = subprocess.run([*command, "--check"], capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual((self.project / updater.MANIFEST_NAME).read_bytes(), before)
        self.assertEqual(source.read_bytes(), original)

    def test_check_rejects_duplicate_json_keys_and_bool_schema(self):
        expected = self.generate()
        wrong_schema = dict(expected, schema=True)
        self.save_manifest(wrong_schema)
        with self.assertRaisesRegex(updater.ManifestError, "stale"):
            updater.check_manifest(self.project, expected)
        self.write(updater.MANIFEST_NAME, '{"schema":1,"schema":1}')
        with self.assertRaisesRegex(updater.ManifestError, "Duplicate"):
            updater.check_manifest(self.project, expected)

    def test_cli_invalid_source_reports_failure_without_traceback_or_writes(self):
        self.write("unreviewed.py", "synthetic only\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = updater.main(["--project", str(self.project), "--include-new", "../outside.py"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Unsafe update path", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertFalse((self.project / updater.MANIFEST_NAME).exists())

    def test_project_subdirectory_is_not_accepted_as_git_root(self):
        with self.assertRaisesRegex(updater.ManifestError, "actual Git root"):
            updater.generate_manifest(self.project / "omnisonic")

    def test_git_read_timeout_is_reported_without_partial_manifest_output(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(
                updater.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 30)
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = updater.main(["--project", str(self.project)])
        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("exceeded 30 seconds", stderr.getvalue())

    def test_json_output_is_ascii_safe_for_windows_consoles(self):
        text = updater.manifest_json({"files": [{"path": "docs/\u4e2d.txt", "sha256": "a" * 64}]})
        text.encode("ascii")
        self.assertEqual(json.loads(text)["files"][0]["path"], "docs/\u4e2d.txt")


if __name__ == "__main__":
    unittest.main()
