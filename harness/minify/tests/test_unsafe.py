import tempfile, unittest, shutil
from pathlib import Path
from harness.minify.lib import unsafe as U

class TestUnsafe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self.tmp.name) / "home")
        self.cwd = str(Path(self.tmp.name) / "proj")
    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_by_default(self):
        self.assertEqual(U.load(self.cwd, home=self.home), set())

    def test_mark_then_load(self):
        U.mark(self.cwd, "py", "no formatter found", home=self.home)
        self.assertEqual(U.load(self.cwd, home=self.home), {"py"})

    def test_mark_is_idempotent(self):
        U.mark(self.cwd, "py", "r1", home=self.home)
        U.mark(self.cwd, "py", "r2", home=self.home)
        self.assertEqual(U.load(self.cwd, home=self.home), {"py"})

    def test_clear_removes_and_reports(self):
        U.mark(self.cwd, "py", "r", home=self.home)
        self.assertTrue(U.clear(self.cwd, "py", home=self.home))
        self.assertEqual(U.load(self.cwd, home=self.home), set())

    def test_clear_missing_returns_false(self):
        self.assertFalse(U.clear(self.cwd, "py", home=self.home))

    def test_malformed_file_reads_as_empty(self):
        p = U.path(self.cwd, home=self.home)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{{{ not json")
        self.assertEqual(U.load(self.cwd, home=self.home), set())

    def test_mark_degrades_when_mkdir_fails(self):
        # Create a file where the harness directory should be, forcing mkdir to fail
        p = U.path(self.cwd, home=self.home)
        p.parent.parent.mkdir(parents=True, exist_ok=True)
        p.parent.write_text("blocking file")
        # mark() should not raise, just degrade
        U.mark(self.cwd, "py", "reason", home=self.home)
        # load() should still work (returns empty since write failed)
        self.assertEqual(U.load(self.cwd, home=self.home), set())

    def test_mark_degrades_when_write_fails(self):
        # Create the harness directory but make unsafe.json a directory to block write
        p = U.path(self.cwd, home=self.home)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.mkdir()
        # mark() should not raise, just degrade
        U.mark(self.cwd, "py", "reason", home=self.home)
        # load() should still work (returns empty since write failed)
        self.assertEqual(U.load(self.cwd, home=self.home), set())

    def test_clear_degrades_when_write_fails(self):
        import os
        # First, create a successful entry
        U.mark(self.cwd, "py", "reason", home=self.home)
        self.assertEqual(U.load(self.cwd, home=self.home), {"py"})
        # Make unsafe.json read-only to block write (but allow read)
        p = U.path(self.cwd, home=self.home)
        p.chmod(0o444)
        try:
            # clear() should not raise; write fails, so returns False
            self.assertFalse(U.clear(self.cwd, "py", home=self.home))
            # On-disk state must match return value: entry still present
            self.assertEqual(U.load(self.cwd, home=self.home), {"py"})
        finally:
            # Restore write permission for temp directory cleanup
            p.chmod(0o644)

    def test_clear_with_deleted_parent_returns_false(self):
        # Mark an extension
        U.mark(self.cwd, "py", "reason", home=self.home)
        self.assertEqual(U.load(self.cwd, home=self.home), {"py"})
        # Delete the parent directory entirely
        p = U.path(self.cwd, home=self.home)
        shutil.rmtree(p.parent)
        # clear() should not raise, should return False (can't read file, so ext not found)
        self.assertFalse(U.clear(self.cwd, "py", home=self.home))
        # load() should still work (returns empty since directory doesn't exist)
        self.assertEqual(U.load(self.cwd, home=self.home), set())

    def test_clear_one_extension_preserves_others(self):
        # Mark two extensions
        U.mark(self.cwd, "py", "no formatter", home=self.home)
        U.mark(self.cwd, "rs", "no formatter", home=self.home)
        self.assertEqual(U.load(self.cwd, home=self.home), {"py", "rs"})
        # Clear one
        self.assertTrue(U.clear(self.cwd, "py", home=self.home))
        # Verify the other is preserved
        self.assertEqual(U.load(self.cwd, home=self.home), {"rs"})

if __name__ == "__main__":
    unittest.main()
