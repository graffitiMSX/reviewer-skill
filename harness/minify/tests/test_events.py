import json, tempfile, unittest
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
        self.assertIn(E.latest_session(str(self.cwd), home=str(self.home)).stem, {"s1", "s2"})

if __name__ == "__main__":
    unittest.main()
