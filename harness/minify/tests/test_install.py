"""install.sh/uninstall.sh must never clobber or delete a file this harness did not
create. Exercised only against throwaway CLAUDE_HOME/BIN_DIR directories -- never the
real ~/.claude."""
import os, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # harness/minify
INSTALL = ROOT / "install.sh"
UNINSTALL = ROOT / "uninstall.sh"


class TestInstallUninstallRefuseForeignFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.claude_home = Path(self.tmp.name) / "claude"
        self.bin_dir = Path(self.tmp.name) / "bin"
        self.claude_home.mkdir()
        self.bin_dir.mkdir()
        (self.claude_home / "settings.json").write_text("{}")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, script):
        env = dict(os.environ)
        env["CLAUDE_HOME"] = str(self.claude_home)
        env["BIN_DIR"] = str(self.bin_dir)
        return subprocess.run([str(script)], env=env, capture_output=True, text=True)

    def test_install_refuses_a_real_file_at_the_destination(self):
        (self.bin_dir / "minread").write_text("#!/bin/sh\necho not ours\n")
        result = self.run_script(INSTALL)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("minread", result.stderr)
        self.assertEqual((self.bin_dir / "minread").read_text(), "#!/bin/sh\necho not ours\n")

    def test_install_refuses_a_symlink_pointing_elsewhere(self):
        elsewhere = Path(self.tmp.name) / "elsewhere.md"
        elsewhere.write_text("not ours")
        (self.claude_home / "output-styles").mkdir()
        (self.claude_home / "output-styles" / "minified.md").symlink_to(elsewhere)
        result = self.run_script(INSTALL)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("minified.md", result.stderr)
        self.assertEqual(
            os.readlink(self.claude_home / "output-styles" / "minified.md"), str(elsewhere)
        )

    def test_uninstall_leaves_a_real_file_in_place(self):
        (self.bin_dir / "minread").write_text("not ours")
        result = self.run_script(UNINSTALL)
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.bin_dir / "minread").exists())
        self.assertEqual((self.bin_dir / "minread").read_text(), "not ours")
        self.assertIn("minread", result.stderr)

    def test_uninstall_leaves_a_symlink_pointing_elsewhere_in_place(self):
        elsewhere = Path(self.tmp.name) / "elsewhere-bin"
        elsewhere.write_text("not ours")
        (self.bin_dir / "minify-harness").symlink_to(elsewhere)
        result = self.run_script(UNINSTALL)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(os.readlink(self.bin_dir / "minify-harness"), str(elsewhere))
        self.assertIn("minify-harness", result.stderr)


if __name__ == "__main__":
    unittest.main()
