import tempfile, unittest
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

if __name__ == "__main__":
    unittest.main()
