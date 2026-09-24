import subprocess, tempfile, unittest
from pathlib import Path
from harness.minify.lib.churn import changed_a, changed_b, churn_outside, git_pre_image

class TestChurn(unittest.TestCase):
    def test_changed_b_reports_lines_in_b(self):
        self.assertEqual(changed_b("a\nb\nc\n", "a\nB\nc\n"), {2})

    def test_changed_a_reports_lines_in_a(self):
        self.assertEqual(changed_a("a\nb\nc\n", "a\nc\n"), {2})

    def test_insertions_count_in_b_only(self):
        self.assertEqual(changed_b("a\nc\n", "a\nb\nc\n"), {2})
        self.assertEqual(changed_a("a\nc\n", "a\nb\nc\n"), set())

    def test_no_churn_when_formatting_only_touches_my_lines(self):
        pre  = "const a = 1;\nconst b = 2;\n"
        mine = "const a=1;\nconst b = 2;\n"       # I edited line 1
        fmt  = "const a = 1;\nconst b = 2;\n"     # formatter fixed line 1
        self.assertEqual(churn_outside(pre, mine, fmt), 0)

    def test_churn_when_formatting_touches_untouched_lines(self):
        pre  = "const a = 1;\nlet   x=9;\nlet   y=8;\n"
        mine = "const a=1;\nlet   x=9;\nlet   y=8;\n"
        fmt  = "const a = 1;\nlet x = 9;\nlet y = 8;\n"   # lines 2-3 were never mine
        self.assertEqual(churn_outside(pre, mine, fmt), 2)

    def test_new_file_has_no_churn(self):
        self.assertEqual(churn_outside("", "a=1\n", "a = 1\n"), 0)

    def test_git_pre_image_reads_head(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
            Path(d, "a.ts").write_text("const a = 1;\n")
            subprocess.run(["git", "add", "a.ts"], cwd=d, check=True)
            subprocess.run(["git", "commit", "-qm", "x"], cwd=d, check=True)
            Path(d, "a.ts").write_text("const a=1;\n")
            self.assertEqual(git_pre_image(d, "a.ts"), "const a = 1;\n")

    def test_git_pre_image_of_untracked_file_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            Path(d, "new.ts").write_text("x")
            self.assertEqual(git_pre_image(d, "new.ts"), "")

    def test_git_pre_image_outside_repo_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(git_pre_image(d, "a.ts"), "")

    def test_git_pre_image_with_nul_in_filename_degrades(self):
        # Task 5 found that subprocess.run raises ValueError on NUL bytes in arguments.
        # FIX 6 (minor): this is a genuine retrieval failure, not "untracked", so it
        # must degrade to None -- distinguishable from the legitimate "" cases above --
        # rather than raise.
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            self.assertIsNone(git_pre_image(d, "file\x00name"))

    def test_git_pre_image_with_binary_content_degrades(self):
        # git show on a binary/mis-encoded file raises UnicodeDecodeError. FIX 6
        # (minor): a genuine retrieval failure must degrade to None, not "" -- the
        # file IS tracked and git DID answer, we just could not decode it, so
        # treating it the same as "untracked" would hide a real failure.
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
            Path(d, "binary").write_bytes(b'\x80\x81\x82')
            subprocess.run(["git", "add", "binary"], cwd=d, check=True)
            subprocess.run(["git", "commit", "-qm", "x"], cwd=d, check=True)
            self.assertIsNone(git_pre_image(d, "binary"))

if __name__ == "__main__":
    unittest.main()
