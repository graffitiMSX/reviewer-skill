import json, os, tempfile, unittest
from pathlib import Path
from harness.minify.lib import events as E

class TestEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.cwd = Path(self.tmp.name) / "proj"
        (self.cwd / ".claude").mkdir(parents=True)
        (self.home / ".claude").mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()

    def test_project_slug_mirrors_claude_code(self):
        self.assertEqual(E.project_slug("/home/a/projects/rudolf/skills"),
                         "-home-a-projects-rudolf-skills")

    def test_append_then_read_roundtrip(self):
        E.append(str(self.cwd), "s1", {"k": "write", "file": "a.ts"}, home=str(self.home))
        E.append(str(self.cwd), "s1", {"k": "write", "file": "b.ts"}, home=str(self.home))
        rows = E.read_session(str(self.cwd), "s1", home=str(self.home))
        self.assertEqual([r["file"] for r in rows], ["a.ts", "b.ts"])

    def test_log_lives_outside_the_project(self):
        E.append(str(self.cwd), "s1", {"k": "write"}, home=str(self.home))
        p = E.log_path(str(self.cwd), "s1", home=str(self.home))
        self.assertTrue(str(p).startswith(str(self.home)))
        self.assertEqual(list(self.cwd.rglob("*.ndjson")), [])

    def test_read_skips_malformed_lines(self):
        p = E.log_path(str(self.cwd), "s1", home=str(self.home))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"k":"write"}\nnot json\n{"k":"measure"}\n')
        self.assertEqual([r["k"] for r in E.read(p)], ["write", "measure"])

    def test_turn_starts_at_one_and_bumps(self):
        self.assertEqual(E.current_turn(str(self.cwd), "s1", home=str(self.home)), 1)
        self.assertEqual(E.bump_turn(str(self.cwd), "s1", home=str(self.home)), 2)
        self.assertEqual(E.current_turn(str(self.cwd), "s1", home=str(self.home)), 2)

    def test_active_style_from_global_settings(self):
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "minified"}))
        self.assertEqual(E.active_style(str(self.cwd), home=str(self.home)), "minified")

    def test_project_local_settings_override_global(self):
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "minified"}))
        (self.cwd / ".claude" / "settings.local.json").write_text(json.dumps({"outputStyle": "default"}))
        self.assertEqual(E.active_style(str(self.cwd), home=str(self.home)), "default")

    def test_active_style_absent_is_none(self):
        self.assertIsNone(E.active_style(str(self.cwd), home=str(self.home)))

    def test_all_logs_and_latest_session(self):
        E.append(str(self.cwd), "s1", {"k": "write"}, home=str(self.home))
        E.append(str(self.cwd), "s2", {"k": "write"}, home=str(self.home))
        self.assertEqual(len(E.all_logs(str(self.cwd), home=str(self.home))), 2)
        # Set explicit, distinct mtimes: s1 at time 100, s2 at time 200
        p1 = E.log_path(str(self.cwd), "s1", home=str(self.home))
        p2 = E.log_path(str(self.cwd), "s2", home=str(self.home))
        os.utime(p1, (100, 100))
        os.utime(p2, (200, 200))
        # latest_session must return s2 (the genuinely newer one)
        self.assertEqual(E.latest_session(str(self.cwd), home=str(self.home)).stem, "s2")

    def test_project_settings_only(self):
        # Only the project's .claude/settings.json sets outputStyle
        (self.cwd / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "minified"}))
        self.assertEqual(E.active_style(str(self.cwd), home=str(self.home)), "minified")

    def test_later_file_without_setting_does_not_erase(self):
        # Global settings sets outputStyle, project-local exists but doesn't have it
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "minified"}))
        (self.cwd / ".claude" / "settings.local.json").write_text(json.dumps({"other": "value"}))
        # Should still return the value from the global file
        self.assertEqual(E.active_style(str(self.cwd), home=str(self.home)), "minified")

    def test_active_style_skips_non_dict_settings(self):
        # Settings file containing [] (valid JSON but not an object) should be skipped
        (self.home / ".claude" / "settings.json").write_text(json.dumps([]))
        (self.cwd / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "minified"}))
        self.assertEqual(E.active_style(str(self.cwd), home=str(self.home)), "minified")

    def test_read_skips_torn_multibyte_chars(self):
        # A log file whose final line is torn mid multi-byte character
        # should degrade gracefully, returning the earlier valid rows
        p = E.log_path(str(self.cwd), "s1", home=str(self.home))
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write valid JSON, then a torn UTF-8 sequence at the end
        with open(p, "wb") as fh:
            fh.write(b'{"k":"write","file":"valid"}\n{"k":"write","file":"caf\xc3')
        rows = E.read(p)
        # Should return only the valid row, skipping the torn one
        self.assertEqual([r["k"] for r in rows], ["write"])
        self.assertEqual(rows[0]["file"], "valid")

    def test_current_turn_handles_null(self):
        # State file containing {"turn": null} should degrade to 1
        p = E._state_path(str(self.cwd), "s1", home=str(self.home))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"turn": None}))
        self.assertEqual(E.current_turn(str(self.cwd), "s1", home=str(self.home)), 1)

if __name__ == "__main__":
    unittest.main()
