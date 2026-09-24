import contextlib, io, json, os, shlex, stat, subprocess, sys, tempfile, unittest
import unittest.mock as mock
from contextlib import redirect_stdout
from pathlib import Path
from harness.minify.lib.doctor import one_line, verdict
from harness.minify.lib import unsafe as U
from harness.minify.hooks.session_doctor import main

SCRIPT = Path(__file__).resolve().parents[1] / "hooks" / "session_doctor.py"

CLEAN = "#!/bin/sh\nexit 0\n"
DIRTY = "#!/bin/sh\necho 'a.ts' \nexit 1\n"
# Real prettier errors ("No parser could be inferred") on an extension it cannot
# parse, such as .sh -- this stub reproduces that instead of the old stubs, which
# exit 0 unconditionally and so could not catch FIX 2's defect (a permissive stub
# is more forgiving than the real tool it stands in for).
UNSUPPORTED_EXT_FAILS = ("#!/bin/sh\n"
                          "for f in \"$@\"; do\n"
                          "  case \"$f\" in\n"
                          "    *.sh) echo \"No parser could be inferred for $f\" >&2; exit 2 ;;\n"
                          "  esac\n"
                          "done\n"
                          "exit 0\n")

def stub(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)

def recording_stub(path, log):
    """A formatter stub that always reports clean, but first appends every argument it
    received to `log` (one per line) plus an invocation marker -- so a test can assert
    both how many times it ran and what paths it was actually handed."""
    body = (f"#!/bin/sh\necho '---' >> {shlex.quote(str(log))}\n"
            f"printf '%s\\n' \"$@\" >> {shlex.quote(str(log))}\nexit 0\n")
    stub(path, body)

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

    def test_repo_clean_unknown_when_sample_is_clean_but_truncated(self):
        """A clean sample is proof only when nothing was truncated. With MAX_CHECK forced
        below the tracked count, a clean sample must report repo_clean=None (not True),
        because a dirty file could be sitting in the untested remainder."""
        git_repo(self.cwd, {"a.ts": "const a = 1;\n", "b.ts": "const b = 1;\n",
                            "c.ts": "const c = 1;\n"})
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        with mock.patch("harness.minify.lib.doctor.MAX_CHECK", 2):
            v = verdict(str(self.cwd), home=self.home)
        self.assertIsNone(v["repo_clean"])
        self.assertTrue(v["truncated"])
        self.assertEqual(v["checked"], 2)
        self.assertEqual(v["tracked_total"], 3)
        self.assertGreater(v["tracked_total"], v["checked"])

    def test_repo_clean_unknown_with_git_but_no_matching_tracked_files(self):
        """A real git repo where nothing tracked matches a minifiable extension must land
        in the unknown state with checked == 0, not be mistaken for a clean repo."""
        git_repo(self.cwd, {"README.md": "hello\n"})
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        v = verdict(str(self.cwd), home=self.home)
        self.assertIsNone(v["repo_clean"])
        self.assertEqual(v["checked"], 0)

    def test_repo_clean_unknown_when_probe_formatter_not_per_file(self):
        """A per_file=False probe formatter inside a real git repo containing matching
        files must still yield unknown -- distinct from the no-git-repo case, which the
        prior (git-less) per_file=False test could not tell apart from this one."""
        git_repo(self.cwd, {"a.ts": "const a=1;\n"})
        (self.cwd / "package.json").write_text(json.dumps({"scripts": {"format": "prettier -w ."}}))
        v = verdict(str(self.cwd), home=self.home)
        self.assertIsNone(v["repo_clean"])
        self.assertEqual(v["checked"], 0)

    def test_repo_clean_ignores_a_tracked_file_the_probe_formatter_cannot_parse(self):
        """FIX 2: a tracked .sh file must not make a clean .ts repo look dirty just
        because the probe's formatter cannot parse it. Real prettier genuinely errors
        on .sh ('No parser could be inferred'); before the fix, _tracked handed the
        probe every COLLAPSE|DENSE extension indiscriminately, so this one non-.ts
        file would poison check_many's single batch call and flip repo_clean to
        False. The stub errors specifically on .sh, so this only passes if .sh was
        excluded from what the probe was asked to check."""
        git_repo(self.cwd, {"a.ts": "const a = 1;\n", "b.sh": "echo hi\n"})
        stub(self.cwd / "node_modules/.bin/prettier", UNSUPPORTED_EXT_FAILS)
        v = verdict(str(self.cwd), home=self.home)
        self.assertIs(v["repo_clean"], True)
        self.assertEqual(v["checked"], 1)  # only a.ts, not b.sh

    def test_check_many_runs_with_absolute_paths_regardless_of_process_cwd(self):
        """The probe's subprocess has no cwd= of its own (lib/detect.py's check_many does
        not take one), so the paths handed to it must already be absolute -- otherwise the
        whole probe silently depends on the calling process's OS working directory equaling
        the project root, which Task 11's CLI cannot guarantee."""
        log = Path(self.tmp.name) / "argv.log"
        recording_stub(self.cwd / "node_modules/.bin/prettier", log)
        git_repo(self.cwd, {"a.ts": "const a = 1;\n"})
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        with contextlib.chdir(elsewhere):
            v = verdict(str(self.cwd), home=self.home)
        self.assertIs(v["repo_clean"], True)
        text = log.read_text()
        self.assertEqual(text.count("---"), 1)
        # The stub's argv is the check command's own flags (e.g. "--check") plus the
        # paths check_many appended; only the ".ts" arguments are paths to verify.
        paths = [l for l in text.splitlines() if l.endswith(".ts")]
        self.assertTrue(paths, "formatter stub recorded no .ts arguments")
        for p in paths:
            self.assertTrue(os.path.isabs(p), f"path handed to formatter was not absolute: {p!r}")
        self.assertIn(str(self.cwd / "a.ts"), paths)

    def test_one_line_mentions_cleanliness_unknown_for_untruncated_none(self):
        """The non-truncated unknown state (no git repo here) keeps its plain wording,
        distinct from the truncated-sample wording."""
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        v = verdict(str(self.cwd), home=self.home)
        line = one_line(v)
        self.assertIn("cleanliness unknown", line)
        self.assertIn("new files only", line)
        self.assertNotIn("checked", line)

    def test_one_line_mentions_truncated_sample_size(self):
        git_repo(self.cwd, {"a.ts": "const a = 1;\n", "b.ts": "const b = 1;\n",
                            "c.ts": "const c = 1;\n"})
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        with mock.patch("harness.minify.lib.doctor.MAX_CHECK", 2):
            v = verdict(str(self.cwd), home=self.home)
        line = one_line(v)
        self.assertIn("checked 2 of 3", line)
        self.assertIn("cleanliness unknown", line)
        self.assertIn("new files only", line)

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

class TestStdinDecodeGuard(unittest.TestCase):
    """FIX 4: sys.stdin.read() in the __main__ block must not raise past the
    always-exit-0 boundary on non-UTF-8 bytes. main() can't exercise this -- it
    takes already-decoded text -- so this drives the real script as a subprocess
    with raw invalid-UTF-8 bytes on stdin, the way Claude Code actually invokes
    hooks. log_write.py already had this guard; this carries it to
    session_doctor.py."""

    def test_invalid_utf8_stdin_exits_zero(self):
        result = subprocess.run([sys.executable, str(SCRIPT)], input=b"\xff\xfe\x00garbage",
                                 capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)

if __name__ == "__main__":
    unittest.main()
