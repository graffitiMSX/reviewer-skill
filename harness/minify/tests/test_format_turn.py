import io, json, os, stat, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from harness.minify.hooks.format_turn import main
from harness.minify.lib import events as E, unsafe as U

def stub(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)

SPACE_EQUALS = "#!/bin/sh\nsed -i 's/=/ = /g' \"$2\"\n"        # argv: --write FILE
REWRITE_ALL  = "#!/bin/sh\nsed -i 's/$/ /' \"$2\"\n"            # touches every line
FAILING      = "#!/bin/sh\necho 'unexpected token' >&2\nexit 2\n"

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self.tmp.name) / "home")
        self.cwd = Path(self.tmp.name) / "proj"
        (self.cwd / "src").mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()

    def hook_in(self, session="s1"):
        return json.dumps({"session_id": session, "cwd": str(self.cwd), "hook_event_name": "Stop"})

    def log_write(self, rel, turn=1, session="s1"):
        E.append(str(self.cwd), session, {"k": "write", "turn": turn, "tool": "Write",
                                          "file": rel, "ext": rel.rsplit(".", 1)[1],
                                          "class": "collapse", "tok": 0, "chars": 0,
                                          "style": "minified"}, home=self.home)

    def run_hook(self, session="s1"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(self.hook_in(session), home=self.home)
        return rc, buf.getvalue()

    def measures(self, session="s1"):
        return [r for r in E.read_session(str(self.cwd), session, home=self.home) if r["k"] == "measure"]

class TestHappyPath(Base):
    def test_measures_minified_then_formatted(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts")
        rc, _ = self.run_hook()
        self.assertEqual(rc, 0)
        m = self.measures()[0]
        self.assertEqual(m["file"], "src/api.ts")
        self.assertEqual(m["tok_min"], 7)     # const a=1;\n
        self.assertEqual(m["tok_fmt"], 9)     # const a = 1;\n
        self.assertTrue(m["formatter_ok"])
        self.assertEqual(m["formatter"], "prettier@node_modules")
        self.assertEqual((self.cwd / "src/api.ts").read_text(), "const a = 1;\n")

    def test_several_writes_to_one_file_make_one_measurement(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts"); self.log_write("src/api.ts"); self.log_write("src/api.ts")
        self.run_hook()
        self.assertEqual(len(self.measures()), 1)
        self.assertEqual(self.measures()[0]["ops"], ["Write", "Write", "Write"])

    def test_turn_is_bumped_and_next_turn_is_isolated(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("a=1\n")
        self.log_write("src/api.ts", turn=1)
        self.run_hook()
        self.assertEqual(E.current_turn(str(self.cwd), "s1", home=self.home), 2)
        self.log_write("src/other.ts", turn=2)
        (self.cwd / "src/other.ts").write_text("b=2\n")
        self.run_hook()
        self.assertEqual([m["file"] for m in self.measures()], ["src/api.ts", "src/other.ts"])

class TestGuards(Base):
    def test_missing_formatter_marks_unsafe_and_warns(self):
        (self.cwd / "src/sync.py").write_text("a=1\n")
        E.append(str(self.cwd), "s1", {"k": "write", "turn": 1, "tool": "Write", "file": "src/sync.py",
                                       "ext": "py", "class": "dense", "tok": 0, "chars": 0,
                                       "style": "minified"}, home=self.home)
        rc, out = self.run_hook()
        self.assertEqual(rc, 0)
        self.assertEqual(U.load(str(self.cwd), home=self.home), {"py"})
        self.assertIn("src/sync.py", out)
        self.assertIn("no formatter", out.lower())
        m = self.measures()[0]
        self.assertFalse(m["formatter_ok"])
        self.assertIsNone(m["tok_fmt"])

    def test_failing_formatter_warns_but_does_not_mark_unsafe(self):
        stub(self.cwd / "node_modules/.bin/prettier", FAILING)
        (self.cwd / "src/api.ts").write_text("const a=1\n")
        self.log_write("src/api.ts")
        rc, out = self.run_hook()
        self.assertEqual(U.load(str(self.cwd), home=self.home), set())
        self.assertIn("unexpected token", out)
        m = self.measures()[0]
        self.assertFalse(m["formatter_ok"])
        self.assertIsNone(m["tok_fmt"])
        self.assertIsNone(m["chars_fmt"])

    def test_churn_outside_my_edit_is_reported(self):
        import subprocess
        stub(self.cwd / "node_modules/.bin/prettier", REWRITE_ALL)
        subprocess.run(["git", "init", "-q"], cwd=self.cwd, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.cwd, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.cwd, check=True)
        (self.cwd / "src/api.ts").write_text("l1\nl2\nl3\nl4\n")
        subprocess.run(["git", "add", "-A"], cwd=self.cwd, check=True)
        subprocess.run(["git", "commit", "-qm", "x"], cwd=self.cwd, check=True)
        (self.cwd / "src/api.ts").write_text("L1\nl2\nl3\nl4\n")   # only line 1 is mine
        self.log_write("src/api.ts")
        rc, out = self.run_hook()
        self.assertGreaterEqual(self.measures()[0]["churn_outside"], 3)
        self.assertIn("churn", out.lower())

    def test_excluded_file_is_never_formatted(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "README.md").write_text("a=1\n")
        E.append(str(self.cwd), "s1", {"k": "write", "turn": 1, "tool": "Write", "file": "README.md",
                                       "ext": "md", "class": "exclude", "tok": 0, "chars": 0,
                                       "style": "minified"}, home=self.home)
        self.run_hook()
        self.assertEqual(self.measures(), [])
        self.assertEqual((self.cwd / "README.md").read_text(), "a=1\n")

    def test_deleted_file_is_skipped(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        self.log_write("src/gone.ts")
        rc, _ = self.run_hook()
        self.assertEqual(rc, 0)
        self.assertEqual(self.measures(), [])

    def test_formatter_present_but_not_per_file_marks_unsafe(self):
        # No node_modules/.bin/prettier or biome, and npx probing is forced to fail
        # (lib.detect memoizes its npx probe in a module-level _NPX_OK, so the probe
        # function itself must be patched -- patching shutil.which would not un-cache
        # a True/False result set by an earlier test in this process), so detect()
        # falls through to the package.json "format" script, which is per_file=False.
        (self.cwd / "package.json").write_text(json.dumps({"scripts": {"format": "prettier --write ."}}))
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts")
        with mock.patch("harness.minify.lib.detect._npx_prettier_ok", return_value=False):
            rc, out = self.run_hook()
        self.assertEqual(rc, 0)
        self.assertEqual(U.load(str(self.cwd), home=self.home), {"ts"})
        m = self.measures()[0]
        self.assertFalse(m["formatter_ok"])
        self.assertEqual(m["formatter"], "npm-script:format")
        self.assertIn("not per-file", out.lower())
        # untouched: a whole-project formatter must never be run on the session's say-so
        self.assertEqual((self.cwd / "src/api.ts").read_text(), "const a=1;\n")

class TestSafety(Base):
    def test_malformed_stdin_exits_zero(self):
        self.assertEqual(main("nonsense", home=self.home), 0)
        self.assertEqual(main("", home=self.home), 0)

    def test_cwd_null_exits_zero(self):
        payload = json.dumps({"session_id": "s1", "cwd": None})
        self.assertEqual(main(payload, home=self.home), 0)

    def test_cwd_int_exits_zero(self):
        payload = json.dumps({"session_id": "s1", "cwd": 123})
        self.assertEqual(main(payload, home=self.home), 0)

    def test_cwd_list_exits_zero(self):
        payload = json.dumps({"session_id": "s1", "cwd": []})
        self.assertEqual(main(payload, home=self.home), 0)

    def test_write_row_missing_file_field_does_not_stall_the_turn(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        # A malformed write row with no "file" key must be skipped during grouping,
        # not abort it -- otherwise every file in the turn goes unprocessed and,
        # because bump_turn() is never reached, the same malformed row would be
        # re-encountered (and re-fail) on every subsequent Stop call.
        E.append(str(self.cwd), "s1", {"k": "write", "turn": 1, "tool": "Write",
                                       "ext": "ts", "class": "collapse", "tok": 0,
                                       "chars": 0, "style": "minified"}, home=self.home)
        self.log_write("src/api.ts")
        rc, _ = self.run_hook()
        self.assertEqual(rc, 0)
        self.assertEqual([m["file"] for m in self.measures()], ["src/api.ts"])
        self.assertEqual(E.current_turn(str(self.cwd), "s1", home=self.home), 2)

    def test_reentrant_call_is_skipped_by_the_lock(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts")
        lock = E.harness_dir(str(self.cwd), self.home) / "s1.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("held")
        rc, _ = self.run_hook()
        self.assertEqual(rc, 0)
        self.assertEqual(self.measures(), [])

    def test_lock_is_released_after_a_normal_run(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts")
        self.run_hook()
        self.assertFalse((E.harness_dir(str(self.cwd), self.home) / "s1.lock").exists())

    def test_no_output_when_nothing_to_say(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts")
        _, out = self.run_hook()
        self.assertEqual(out.strip(), "")

class TestPerFileGuard(Base):
    """Controller-required guard: one file's processing failure inside the loop
    must not abort the turn for the files that follow it."""

    def test_one_files_failure_does_not_abort_the_remaining_files(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/broken.ts").write_text("const a=1;\n")
        (self.cwd / "src/api.ts").write_text("const b=2;\n")
        # insertion order matters: broken.ts is logged (and therefore processed) first
        self.log_write("src/broken.ts")
        self.log_write("src/api.ts")
        # Force a real, unmocked failure while processing broken.ts: it becomes
        # unreadable after being written, so reading it back inside the hook raises.
        os.chmod(self.cwd / "src/broken.ts", 0)
        try:
            rc, out = self.run_hook()
        finally:
            os.chmod(self.cwd / "src/broken.ts", 0o644)  # let tempdir cleanup remove it
        self.assertEqual(rc, 0)
        files = {m["file"] for m in self.measures()}
        self.assertNotIn("src/broken.ts", files)
        self.assertIn("src/api.ts", files)
        api = next(m for m in self.measures() if m["file"] == "src/api.ts")
        self.assertTrue(api["formatter_ok"])
        self.assertEqual((self.cwd / "src/api.ts").read_text(), "const b = 2;\n")
        self.assertIn("src/broken.ts", out)
        # the turn still closes even though one file failed
        self.assertEqual(E.current_turn(str(self.cwd), "s1", home=self.home), 2)

class TestOuterGuard(Base):
    """Controller-required guard: the lock must be released even when the body
    raises past the per-file guard (the true last-resort path)."""

    def test_outer_failure_in_bump_turn_still_exits_zero_and_releases_lock(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts")
        # Force E.bump_turn to raise a real, unmocked OSError: pre-create the
        # turn-state path as a directory, so write_text() cannot write to it.
        # current_turn() degrades to 1 on this (verified separately), so the
        # loop runs normally and only the trailing bump_turn() call fails.
        state_path = E.harness_dir(str(self.cwd), self.home) / "s1.state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.mkdir()
        rc, out = self.run_hook()
        self.assertEqual(rc, 0)
        self.assertFalse((E.harness_dir(str(self.cwd), self.home) / "s1.lock").exists())
        self.assertIn("internal error", out.lower())
        # the file was measured and formatted before bump_turn's failure surfaced
        self.assertEqual(len(self.measures()), 1)
        self.assertTrue(self.measures()[0]["formatter_ok"])

if __name__ == "__main__":
    unittest.main()
