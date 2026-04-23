"""Tests for scripts/install.py helpers.

Covers the pure, testable surface — detection, path resolution, pack
parsing, and env-file writing. Interactive flows and subprocess calls
are not exercised here (manual smoke test covers those).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# install.py sits at repo_root/scripts/install.py, not inside the package.
# Add scripts/ to sys.path so we can import it without pip-installing anything.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import install  # type: ignore[import-not-found]  # noqa: E402


class TestDetectPythonOk(unittest.TestCase):
    def test_311_passes(self):
        self.assertTrue(install.detect_python_ok((3, 11, 0)))

    def test_312_passes(self):
        self.assertTrue(install.detect_python_ok((3, 12, 1)))

    def test_313_passes(self):
        self.assertTrue(install.detect_python_ok((3, 13, 5)))

    def test_310_fails(self):
        self.assertFalse(install.detect_python_ok((3, 10, 9)))

    def test_27_fails(self):
        self.assertFalse(install.detect_python_ok((2, 7, 18)))


class TestInstallHintForOs(unittest.TestCase):
    def test_darwin_ffmpeg(self):
        self.assertIn("brew install ffmpeg", install.install_hint_for_os("ffmpeg", "Darwin"))

    def test_linux_ffmpeg(self):
        self.assertIn("apt install ffmpeg", install.install_hint_for_os("ffmpeg", "Linux"))

    def test_windows_ffmpeg(self):
        self.assertIn("choco install ffmpeg", install.install_hint_for_os("ffmpeg", "Windows"))

    def test_unknown_os_returns_empty(self):
        self.assertEqual(install.install_hint_for_os("ffmpeg", "Plan9"), "")

    def test_unknown_tool_returns_empty(self):
        self.assertEqual(install.install_hint_for_os("xyz", "Linux"), "")


class TestDetectFfmpeg(unittest.TestCase):
    def test_found_returns_path(self):
        with mock.patch.object(install.shutil, "which", return_value="/usr/bin/ffmpeg"):
            f = install.detect_ffmpeg()
        self.assertTrue(f.found)
        self.assertEqual(f.detail, "/usr/bin/ffmpeg")
        self.assertFalse(f.blocking)

    def test_missing_is_blocking(self):
        with mock.patch.object(install.shutil, "which", return_value=None):
            with mock.patch.object(install.platform, "system", return_value="Linux"):
                f = install.detect_ffmpeg()
        self.assertFalse(f.found)
        self.assertTrue(f.blocking)
        self.assertIn("apt install ffmpeg", f.install_cmd)


class TestDetectYtdlp(unittest.TestCase):
    def test_missing_is_not_blocking(self):
        with mock.patch.object(install.shutil, "which", return_value=None):
            f = install.detect_ytdlp()
        self.assertFalse(f.found)
        self.assertFalse(f.blocking)  # pip installs it, so not blocking
        self.assertIn("will install", f.detail)


class TestResolveVenvPython(unittest.TestCase):
    def test_posix(self):
        result = install.resolve_venv_python(Path(".venv"), os_name="Linux")
        self.assertEqual(result, Path(".venv") / "bin" / "python")

    def test_windows(self):
        result = install.resolve_venv_python(Path(".venv"), os_name="Windows")
        self.assertEqual(result, Path(".venv") / "Scripts" / "python.exe")


class TestParsePackChoice(unittest.TestCase):
    def test_numeric_map(self):
        self.assertEqual(install.parse_pack_choice("1"), "lite")
        self.assertEqual(install.parse_pack_choice("2"), "full")
        self.assertEqual(install.parse_pack_choice("3"), "dev")

    def test_name_map(self):
        self.assertEqual(install.parse_pack_choice("lite"), "lite")
        self.assertEqual(install.parse_pack_choice("FULL"), "full")  # case-insensitive
        self.assertEqual(install.parse_pack_choice("  dev  "), "dev")  # trims

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            install.parse_pack_choice("xxl")
        with self.assertRaises(ValueError):
            install.parse_pack_choice("4")
        with self.assertRaises(ValueError):
            install.parse_pack_choice("")


class TestFormatFindingRow(unittest.TestCase):
    def test_found_shows_check(self):
        f = install.Finding(name="python", found=True, detail="3.13.5")
        row = install.format_finding_row(f)
        self.assertIn("python", row)
        self.assertIn("3.13.5", row)

    def test_missing_shows_cross(self):
        f = install.Finding(name="ffmpeg", found=False, detail="not on PATH")
        row = install.format_finding_row(f)
        self.assertIn("ffmpeg", row)
        self.assertIn("not on PATH", row)


class TestWriteEnvFile(unittest.TestCase):
    def test_creates_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            install.write_env_file(path, {"GEMINI_API_KEY": "key-abc"})
            content = path.read_text(encoding="utf-8")
        self.assertIn("GEMINI_API_KEY=key-abc", content)

    def test_preserves_existing_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("FOO=bar\n# a comment\nBAZ=qux\n", encoding="utf-8")
            install.write_env_file(path, {"GEMINI_API_KEY": "xyz"})
            content = path.read_text(encoding="utf-8")
        self.assertIn("FOO=bar", content)
        self.assertIn("# a comment", content)
        self.assertIn("BAZ=qux", content)
        self.assertIn("GEMINI_API_KEY=xyz", content)

    def test_replaces_existing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("GEMINI_API_KEY=old-value\nFOO=bar\n", encoding="utf-8")
            install.write_env_file(path, {"GEMINI_API_KEY": "new-value"})
            content = path.read_text(encoding="utf-8")
        self.assertIn("GEMINI_API_KEY=new-value", content)
        self.assertNotIn("GEMINI_API_KEY=old-value", content)
        self.assertIn("FOO=bar", content)  # unrelated line preserved

    def test_no_orphan_tmp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            install.write_env_file(path, {"KEY": "value"})
            leftovers = [p for p in Path(tmp).iterdir() if p.name != ".env"]
        self.assertEqual(leftovers, [], "atomic write must leave no .tmp files behind")

    def test_rejects_newline_in_value(self):
        """Values with \\n would corrupt the .env line format — defensive reject."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            with self.assertRaises(ValueError):
                install.write_env_file(path, {"KEY": "value\nINJECTED=bad"})
            # Must also not leave the file partially written
            self.assertFalse(path.exists())

    def test_rejects_null_in_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            with self.assertRaises(ValueError):
                install.write_env_file(path, {"KEY": "value\x00oops"})


class TestSpinner(unittest.TestCase):
    def test_spinner_starts_and_stops_without_tty(self):
        """When stdout isn't a tty, spinner still works — just falls back."""
        import contextlib
        import io
        with mock.patch.object(install, "_is_tty", return_value=False), \
             contextlib.redirect_stderr(io.StringIO()):
            with install.Spinner("test") as sp:
                sp.update("doing X")
        # No exception raised = pass


class TestArgparse(unittest.TestCase):
    def test_help_exits_zero(self):
        import contextlib
        import io
        parser = install._build_parser()
        # Swallow argparse's help output so it doesn't pollute test runner output.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            parser.parse_args(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("install.py", buf.getvalue())

    def test_non_interactive_flags_parse(self):
        parser = install._build_parser()
        args = parser.parse_args([
            "--yes", "--pack=lite", "--no-venv",
            "--gemini-key=test-key",
            "--skip-smoke-test",
        ])
        self.assertTrue(args.yes)
        self.assertEqual(args.pack, "lite")
        self.assertTrue(args.no_venv)
        self.assertEqual(args.gemini_key, "test-key")
        self.assertTrue(args.skip_smoke_test)

    def test_rejects_unknown_pack(self):
        import contextlib
        import io
        parser = install._build_parser()
        # Swallow argparse's error output too.
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--pack=gigantic"])


if __name__ == "__main__":
    unittest.main()
