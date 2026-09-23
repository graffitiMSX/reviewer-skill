import json, os, shlex, stat, tempfile, unittest
import unittest.mock as mock
from pathlib import Path
from harness.minify.lib.detect import detect

def fake_bin(path, body="#!/bin/sh\nexit 0\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)

def recording_bin(path, log):
    """A formatter stub that always reports clean, but first appends every argument it
    received to `log` (one per line) plus an invocation marker -- so a test can assert
    both how many times it ran and what it was actually handed."""
    body = (f"#!/bin/sh\necho '---' >> {shlex.quote(str(log))}\n"
            f"printf '%s\\n' \"$@\" >> {shlex.quote(str(log))}\nexit 0\n")
    fake_bin(path, body)

class TestDetect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()

    def test_prettier_in_node_modules_wins(self):
        fake_bin(self.root / "node_modules/.bin/prettier")
        fake_bin(self.root / "node_modules/.bin/biome")
        f = detect(str(self.root), "ts")
        self.assertEqual(f.name, "prettier@node_modules")
        self.assertTrue(f.per_file)

    def test_biome_when_prettier_absent(self):
        fake_bin(self.root / "node_modules/.bin/biome")
        self.assertEqual(detect(str(self.root), "css").name, "biome@node_modules")

    def test_ruff_for_python(self):
        fake_bin(self.root / ".venv/bin/ruff")
        self.assertEqual(detect(str(self.root), "py").name, "ruff@venv")

    def test_black_when_ruff_absent(self):
        fake_bin(self.root / ".venv/bin/black")
        self.assertEqual(detect(str(self.root), "py").name, "black@venv")

    def test_npm_script_is_detected_but_not_per_file(self):
        (self.root / "package.json").write_text(json.dumps({"scripts": {"format": "prettier -w ."}}))
        with mock.patch("harness.minify.lib.detect._npx_prettier_ok", return_value=False):
            f = detect(str(self.root), "ts")
        self.assertEqual(f.name, "npm-script:format")
        self.assertFalse(f.per_file)

    def test_nothing_found_is_none(self):
        with mock.patch("harness.minify.lib.detect._npx_prettier_ok", return_value=False):
            self.assertIsNone(detect(str(self.root), "ts"))
        self.assertIsNone(detect(str(self.root), "py"))

    def test_unusable_npx_is_not_offered_as_a_formatter(self):
        with mock.patch("harness.minify.lib.detect._npx_prettier_ok", return_value=False):
            self.assertIsNone(detect(str(self.root), "ts"))
        with mock.patch("harness.minify.lib.detect._npx_prettier_ok", return_value=True):
            self.assertEqual(detect(str(self.root), "ts").name, "npx:prettier")

    def test_unknown_extension_is_none(self):
        fake_bin(self.root / "node_modules/.bin/prettier")
        self.assertIsNone(detect(str(self.root), "png"))

    def test_format_reports_failure_with_stderr(self):
        fake_bin(self.root / ".venv/bin/ruff", "#!/bin/sh\necho 'syntax error' >&2\nexit 2\n")
        ok, err = detect(str(self.root), "py").format(str(self.root / "x.py"))
        self.assertFalse(ok)
        self.assertIn("syntax error", err)

    def test_format_reports_success(self):
        fake_bin(self.root / ".venv/bin/ruff")
        ok, err = detect(str(self.root), "py").format(str(self.root / "x.py"))
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_format_with_nul_byte_in_path_degrades_gracefully(self):
        """NUL bytes in paths raise ValueError; _run must catch it and return (False, msg)."""
        fake_bin(self.root / ".venv/bin/ruff")
        fmt = detect(str(self.root), "py")
        ok, err = fmt.format(str(self.root / "x.py") + "\0bad")
        self.assertFalse(ok)
        self.assertIn("embedded null byte", err)

    def test_check_many_empty_list_is_clean(self):
        fake_bin(self.root / ".venv/bin/ruff")
        ok, out = detect(str(self.root), "py").check_many([])
        self.assertTrue(ok)
        self.assertEqual(out, "")

    def test_check_many_one_invocation_for_many_paths(self):
        """A stub that ignores argv can't tell one call from three sequential calls --
        record what actually ran so the test can assert exactly one invocation happened
        and all three paths were handed to it together."""
        log = self.root / "invocations.log"
        recording_bin(self.root / ".venv/bin/ruff", log)
        fmt = detect(str(self.root), "py")
        paths = [str(self.root / f"x{i}.py") for i in range(3)]
        ok, out = fmt.check_many(paths)
        self.assertTrue(ok)
        text = log.read_text()
        self.assertEqual(text.count("---"), 1)
        for p in paths:
            self.assertIn(p, text)

    def test_check_many_reports_failure(self):
        fake_bin(self.root / ".venv/bin/ruff", "#!/bin/sh\necho 'not formatted' >&2\nexit 1\n")
        fmt = detect(str(self.root), "py")
        ok, out = fmt.check_many([str(self.root / "x.py")])
        self.assertFalse(ok)
        self.assertIn("not formatted", out)

    def test_check_many_with_nul_byte_in_path_degrades_gracefully(self):
        """An embedded NUL in one of the paths must not raise past check_many."""
        fake_bin(self.root / ".venv/bin/ruff")
        fmt = detect(str(self.root), "py")
        ok, err = fmt.check_many([str(self.root / "x.py") + "\0bad"])
        self.assertFalse(ok)
        self.assertIn("embedded null byte", err)

    def test_check_many_missing_executable_degrades_gracefully(self):
        """A formatter whose binary vanished between detect() and use raises OSError (FileNotFoundError);
        check_many must catch it, not propagate it."""
        from harness.minify.lib.detect import Formatter
        fmt = Formatter("ghost", ["/no/such/executable"], ["/no/such/executable"])
        ok, err = fmt.check_many([str(self.root / "x.py")])
        self.assertFalse(ok)
        self.assertTrue(err)

if __name__ == "__main__":
    unittest.main()
