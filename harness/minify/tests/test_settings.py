import json, os, tempfile, unittest
import unittest.mock as mock
from pathlib import Path
from harness.minify.lib.settings import MARKER, SettingsError, patch, unpatch

EXISTING = {
    "permissions": {"defaultMode": "auto"},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]}],
        "SessionStart": [{"matcher": "*", "hooks": [
            {"type": "command", "command": "bash '/home/x/.claude/hooks/herdr-agent-state.sh' session",
             "timeout": 10}]}],
    },
}

class TestPatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "settings.json"
        self.p.write_text(json.dumps(EXISTING, indent=2))
        self.root = "/opt/harness/minify"
    def tearDown(self):
        self.tmp.cleanup()

    def load(self):
        return json.loads(self.p.read_text())

    def commands(self, event):
        return [h["command"] for g in self.load()["hooks"].get(event, []) for h in g["hooks"]]

    def test_adds_all_three_hooks(self):
        patch(str(self.p), self.root)
        self.assertTrue(any("log_write.py" in c for c in self.commands("PostToolUse")))
        self.assertTrue(any("format_turn.py" in c for c in self.commands("Stop")))
        self.assertTrue(any("session_doctor.py" in c for c in self.commands("SessionStart")))

    def test_preserves_the_rtk_hook(self):
        patch(str(self.p), self.root)
        self.assertIn("rtk hook claude", self.commands("PreToolUse"))

    def test_preserves_the_existing_session_start_hook(self):
        patch(str(self.p), self.root)
        cmds = self.commands("SessionStart")
        self.assertTrue(any("herdr-agent-state.sh" in c for c in cmds))
        self.assertEqual(len(cmds), 2)

    def test_joins_the_existing_star_matcher_group(self):
        patch(str(self.p), self.root)
        groups = [g for g in self.load()["hooks"]["SessionStart"] if g["matcher"] == "*"]
        self.assertEqual(len(groups), 1)

    def test_post_tool_use_matcher_is_write_or_edit(self):
        patch(str(self.p), self.root)
        self.assertEqual(self.load()["hooks"]["PostToolUse"][0]["matcher"], "Write|Edit")

    def test_patch_is_idempotent(self):
        patch(str(self.p), self.root)
        patch(str(self.p), self.root)
        self.assertEqual(len([c for c in self.commands("SessionStart") if MARKER in c]), 1)
        self.assertEqual(len(self.commands("Stop")), 1)

    def test_unpatch_restores_the_original_exactly(self):
        patch(str(self.p), self.root)
        unpatch(str(self.p))
        self.assertEqual(self.load(), EXISTING)

    def test_unpatch_on_a_clean_file_changes_nothing(self):
        unpatch(str(self.p))
        self.assertEqual(self.load(), EXISTING)

    def test_patch_creates_a_backup(self):
        patch(str(self.p), self.root)
        self.assertTrue(Path(str(self.p) + ".minify-bak").exists())

    def test_patch_on_a_settings_file_with_no_hooks_key(self):
        self.p.write_text(json.dumps({"theme": "dark"}))
        patch(str(self.p), self.root)
        self.assertEqual(self.load()["theme"], "dark")
        self.assertTrue(any("format_turn.py" in c for c in self.commands("Stop")))
        unpatch(str(self.p))
        self.assertEqual(self.load(), {"theme": "dark"})

    def test_patch_on_unparseable_json_raises_and_leaves_the_file_untouched(self):
        self.p.write_text("{not valid json")
        before = self.p.read_bytes()
        with self.assertRaises(SettingsError):
            patch(str(self.p), self.root)
        self.assertEqual(self.p.read_bytes(), before)
        self.assertFalse(Path(str(self.p) + ".minify-bak").exists())

    def test_marker_is_independent_of_the_root_path(self):
        # A root whose name does not contain "minify" must still be detected as
        # ours on a second patch, and fully removable by unpatch.
        root = "/opt/some-other-checkout-name"
        patch(str(self.p), root)
        patch(str(self.p), root)
        self.assertEqual(len([c for c in self.commands("Stop") if MARKER in c]), 1)
        unpatch(str(self.p))
        self.assertEqual(self.load(), EXISTING)

    def test_patching_again_with_a_different_root_replaces_the_stale_command(self):
        patch(str(self.p), "/opt/harness-a")
        patch(str(self.p), "/opt/harness-b")
        for event in ("SessionStart", "PostToolUse", "Stop"):
            ours = [c for c in self.commands(event) if MARKER in c]
            self.assertEqual(len(ours), 1)
            self.assertIn("harness-b", ours[0])
            self.assertNotIn("harness-a", ours[0])

    def test_second_install_does_not_overwrite_the_backup(self):
        patch(str(self.p), self.root)
        backup_path = Path(str(self.p) + ".minify-bak")
        first_backup = backup_path.read_text()
        patch(str(self.p), self.root)
        second_backup = backup_path.read_text()
        self.assertEqual(first_backup, second_backup)
        self.assertEqual(json.loads(second_backup), EXISTING)

    # -- FIX 8: unpatch also takes a backup ------------------------------------

    def test_unpatch_creates_a_backup(self):
        patch(str(self.p), self.root)
        unpatch(str(self.p))
        backup = Path(str(self.p) + ".minify-bak")
        self.assertTrue(backup.exists())

    def test_unpatch_on_a_never_installed_file_creates_no_backup(self):
        # Nothing to remove -- unpatch is a genuine no-op, so it must not spuriously
        # create (or overwrite) a backup of a state nothing is about to change.
        unpatch(str(self.p))
        self.assertFalse(Path(str(self.p) + ".minify-bak").exists())

    # -- FIX 8: atomic writes ---------------------------------------------------

    def test_save_failure_leaves_real_settings_untouched(self):
        """Simulates a crash mid-write (e.g. ENOSPC, which this machine actually hit
        during this project's own development). The write must go to a temp file
        first, so a failure there must never truncate or corrupt the real file."""
        original = self.p.read_bytes()
        with mock.patch("harness.minify.lib.settings.json.dump",
                         side_effect=OSError("No space left on device")):
            with self.assertRaises(OSError):
                patch(str(self.p), self.root)
        self.assertEqual(self.p.read_bytes(), original)
        leftovers = [f.name for f in self.p.parent.iterdir()
                     if f.name.startswith(".minify-harness-") and f.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_save_writes_atomically_via_replace(self):
        """The temp file must live in the same directory as the target (so
        os.replace is atomic on the same filesystem) and must be gone afterwards --
        proof the write went through a temp-then-replace path rather than truncating
        settings.json in place."""
        seen_tmp_paths = []
        real_replace = os.replace
        def spying_replace(src, dst):
            seen_tmp_paths.append(src)
            return real_replace(src, dst)
        with mock.patch("harness.minify.lib.settings.os.replace", side_effect=spying_replace):
            patch(str(self.p), self.root)
        self.assertEqual(len(seen_tmp_paths), 1)
        self.assertEqual(os.path.dirname(seen_tmp_paths[0]), str(self.p.parent))
        self.assertNotEqual(seen_tmp_paths[0], str(self.p))
        self.assertFalse(os.path.exists(seen_tmp_paths[0]))  # replaced away

    # -- Minor: settings.json whose top level is valid JSON but not an object ---

    def test_non_object_json_raises_settings_error_not_attributeerror(self):
        for literal in ("[]", "null", '"x"', "42"):
            with self.subTest(literal=literal):
                self.p.write_text(literal)
                before = self.p.read_bytes()
                with self.assertRaises(SettingsError):
                    patch(str(self.p), self.root)
                self.assertEqual(self.p.read_bytes(), before)

    # -- Minor: _load must not treat every OSError as "no file yet" -------------

    def test_permission_denied_is_not_treated_as_no_file_yet(self):
        """A blanket `except OSError` would silently treat permission-denied the
        same as a missing file and proceed to try to overwrite it. Narrowed to
        FileNotFoundError only, so anything else propagates."""
        self.p.chmod(0o000)
        try:
            with self.assertRaises(PermissionError):
                patch(str(self.p), self.root)
        finally:
            self.p.chmod(0o644)  # allow tempdir cleanup

if __name__ == "__main__":
    unittest.main()
