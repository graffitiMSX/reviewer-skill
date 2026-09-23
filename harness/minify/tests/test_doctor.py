import io, json, stat, subprocess, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from harness.minify.lib.doctor import one_line, verdict
from harness.minify.lib import unsafe as U
from harness.minify.hooks.session_doctor import main

CLEAN = "#!/bin/sh\nexit 0\n"
DIRTY = "#!/bin/sh\necho 'a.ts' \nexit 1\n"

def stub(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)

def git_repo(root, files):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    for rel, body in files.items():
        p = Path(root, rel); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)

class TestVerdict(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self.tmp.name) / "home")
        self.cwd = Path(self.tmp.name) / "proj"
        self.cwd.mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()

    def test_ts_is_safe_when_prettier_exists(self):
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        v = verdict(str(self.cwd), home=self.home)
        self.assertIn("ts", v["safe"])
        self.assertEqual(v["formatters"]["ts"], "prettier@node_modules")

    def test_py_is_blocked_without_a_formatter(self):
        v = verdict(str(self.cwd), home=self.home)
        self.assertNotIn("py", v["safe"])
        self.assertIn("py", v["blocked"])

    def test_unsafe_registry_blocks_a_language_with_a_formatter(self):
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        U.mark(str(self.cwd), "ts", "no formatter", home=self.home)
        v = verdict(str(self.cwd), home=self.home)
        self.assertNotIn("ts", v["safe"])
        self.assertIn("marked unsafe", v["blocked"]["ts"])

    def test_repo_clean_true(self):
        git_repo(self.cwd, {"a.ts": "const a = 1;\n"})
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        v = verdict(str(self.cwd), home=self.home)
        self.assertIs(v["repo_clean"], True)
        self.assertGreaterEqual(v["checked"], 1)

    def test_repo_clean_false(self):
        git_repo(self.cwd, {"a.ts": "const a=1;\n"})
        stub(self.cwd / "node_modules/.bin/prettier", DIRTY)
        self.assertIs(verdict(str(self.cwd), home=self.home)["repo_clean"], False)

    def test_repo_clean_unknown_without_git(self):
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        self.assertIsNone(verdict(str(self.cwd), home=self.home)["repo_clean"])

    def test_non_per_file_formatter_is_blocked_not_safe(self):
        """A detected formatter that can only run whole-project (npm-script:format) must not
        be offered as safe -- verdict() has to check f.per_file, not just f is not None."""
        (self.cwd / "package.json").write_text(json.dumps({"scripts": {"format": "prettier -w ."}}))
        v = verdict(str(self.cwd), home=self.home)
        self.assertNotIn("ts", v["safe"])
        self.assertIn("ts", v["blocked"])
        self.assertIn("not per-file", v["blocked"]["ts"])

    def test_one_line_mentions_safe_blocked_and_rule(self):
        git_repo(self.cwd, {"a.ts": "const a=1;\n"})
        stub(self.cwd / "node_modules/.bin/prettier", DIRTY)
        line = one_line(verdict(str(self.cwd), home=self.home))
        self.assertIn("safe=", line)
        self.assertIn("py", line)
        self.assertIn("new files only", line)

class TestSessionStartHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self.tmp.name) / "home")
        self.cwd = Path(self.tmp.name) / "proj"
        self.cwd.mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()

    def test_emits_additional_context(self):
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(json.dumps({"cwd": str(self.cwd), "session_id": "s1",
                                  "hook_event_name": "SessionStart", "source": "startup"}),
                      home=self.home)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("safe=", payload["hookSpecificOutput"]["additionalContext"])

    def test_malformed_stdin_exits_zero_silently(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main("garbage", home=self.home), 0)
        self.assertEqual(buf.getvalue().strip(), "")

    def test_cwd_null_returns_zero_silently(self):
        """A valid-JSON payload with cwd: null must not raise past the guard (task 8 regression)."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(json.dumps({"cwd": None, "session_id": "s1",
                                  "hook_event_name": "SessionStart", "source": "startup"}),
                      home=self.home)
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "")

    def test_cwd_non_string_returns_zero_silently(self):
        """A non-string cwd (e.g. an int or a list) must be rejected before path code sees it."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(json.dumps({"cwd": 42, "session_id": "s1",
                                  "hook_event_name": "SessionStart", "source": "startup"}),
                      home=self.home)
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "")

if __name__ == "__main__":
    unittest.main()
