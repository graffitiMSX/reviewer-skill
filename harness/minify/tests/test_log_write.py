import json, tempfile, unittest
from pathlib import Path
from harness.minify.hooks.log_write import main, payload_of
from harness.minify.lib import events as E

def hook_input(cwd, tool, tool_input, session="s1"):
    return json.dumps({"session_id": session, "cwd": str(cwd),
                       "hook_event_name": "PostToolUse",
                       "tool_name": tool, "tool_input": tool_input})

class TestPayload(unittest.TestCase):
    def test_write_uses_content(self):
        self.assertEqual(payload_of("Write", {"file_path": "/a.ts", "content": "x=1"}), "x=1")
    def test_edit_uses_new_string(self):
        self.assertEqual(payload_of("Edit", {"file_path": "/a.ts", "old_string": "a", "new_string": "b"}), "b")
    def test_unknown_tool_is_none(self):
        self.assertIsNone(payload_of("Bash", {"command": "ls"}))
    def test_never_reads_tool_result(self):
        self.assertIsNone(payload_of("Write", {"file_path": "/a.ts"}))

class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.cwd = Path(self.tmp.name) / "proj"
        (self.cwd / "src").mkdir(parents=True)
        (self.home / ".claude").mkdir(parents=True)
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "minified"}))
    def tearDown(self):
        self.tmp.cleanup()

    def rows(self, session="s1"):
        return E.read_session(str(self.cwd), session, home=str(self.home))

    def test_logs_a_write_event(self):
        rc = main(hook_input(self.cwd, "Write", {"file_path": "src/api.ts", "content": "const a=1;\n"}),
                  home=str(self.home))
        self.assertEqual(rc, 0)
        r = self.rows()[0]
        self.assertEqual(r["k"], "write")
        self.assertEqual(r["file"], "src/api.ts")
        self.assertEqual(r["ext"], "ts")
        self.assertEqual(r["class"], "collapse")
        self.assertEqual(r["tool"], "Write")
        self.assertEqual(r["turn"], 1)
        self.assertEqual(r["style"], "minified")
        self.assertEqual(r["tok"], 7)
        self.assertEqual(r["chars"], 11)

    def test_absolute_path_is_stored_relative_to_cwd(self):
        main(hook_input(self.cwd, "Write", {"file_path": str(self.cwd / "src/api.ts"), "content": "a"}),
             home=str(self.home))
        self.assertEqual(self.rows()[0]["file"], "src/api.ts")

    def test_excluded_class_is_not_logged(self):
        main(hook_input(self.cwd, "Write", {"file_path": "README.md", "content": "# hi"}), home=str(self.home))
        self.assertEqual(self.rows(), [])

    def test_non_write_tool_is_not_logged(self):
        main(hook_input(self.cwd, "Bash", {"command": "ls"}), home=str(self.home))
        self.assertEqual(self.rows(), [])

    def test_malformed_stdin_exits_zero_and_logs_nothing(self):
        self.assertEqual(main("not json at all", home=str(self.home)), 0)
        self.assertEqual(main("", home=str(self.home)), 0)

    def test_missing_cwd_exits_zero(self):
        self.assertEqual(main(json.dumps({"tool_name": "Write", "tool_input": {}}), home=str(self.home)), 0)

    def test_style_absent_is_recorded_as_none(self):
        (self.home / ".claude" / "settings.json").write_text("{}")
        main(hook_input(self.cwd, "Write", {"file_path": "src/api.ts", "content": "a"}), home=str(self.home))
        self.assertIsNone(self.rows()[0]["style"])

    def test_absolute_path_outside_cwd_is_not_logged(self):
        rc = main(hook_input(self.cwd, "Write", {"file_path": "/tmp/outside.ts", "content": "x"}),
                  home=str(self.home))
        self.assertEqual(rc, 0)
        self.assertEqual(self.rows(), [])

    def test_relative_path_escaping_cwd_is_not_logged(self):
        rc = main(hook_input(self.cwd, "Write", {"file_path": "../outside.ts", "content": "x"}),
                  home=str(self.home))
        self.assertEqual(rc, 0)
        self.assertEqual(self.rows(), [])

    def test_file_named_dotdotfoo_inside_project_is_logged(self):
        (self.cwd / "..foo.ts").write_text("content")
        rc = main(hook_input(self.cwd, "Write", {"file_path": "..foo.ts", "content": "x"}),
                  home=str(self.home))
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["file"], "..foo.ts")

    def test_non_dict_tool_input_exits_zero(self):
        rc = main(hook_input(self.cwd, "Write", "not a dict"), home=str(self.home))
        self.assertEqual(rc, 0)
        self.assertEqual(self.rows(), [])

    def test_non_string_cwd_exits_zero(self):
        stdin = json.dumps({"cwd": 123, "tool_name": "Write", "tool_input": {"file_path": "a.ts", "content": "x"}})
        rc = main(stdin, home=str(self.home))
        self.assertEqual(rc, 0)
        self.assertEqual(self.rows(), [])

    def test_relative_path_with_dotdot_in_middle_escaping_cwd_is_not_logged(self):
        rc = main(hook_input(self.cwd, "Write", {"file_path": "src/../../outside.ts", "content": "x"}),
                  home=str(self.home))
        self.assertEqual(rc, 0)
        self.assertEqual(self.rows(), [])

    def test_relative_path_with_parent_refs_is_normalized(self):
        main(hook_input(self.cwd, "Write", {"file_path": "src/../api.ts", "content": "x"}),
             home=str(self.home))
        self.assertEqual(self.rows()[0]["file"], "api.ts")

    def test_relative_path_with_leading_dot_is_normalized(self):
        main(hook_input(self.cwd, "Write", {"file_path": "./src/api.ts", "content": "x"}),
             home=str(self.home))
        self.assertEqual(self.rows()[0]["file"], "src/api.ts")

    def test_file_named_dotdotfoo_after_normalization_is_logged_correctly(self):
        (self.cwd / "..foo.ts").write_text("content")
        main(hook_input(self.cwd, "Write", {"file_path": "..foo.ts", "content": "x"}),
             home=str(self.home))
        self.assertEqual(self.rows()[0]["file"], "..foo.ts")

if __name__ == "__main__":
    unittest.main()
