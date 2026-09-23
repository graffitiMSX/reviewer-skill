import importlib.machinery, importlib.util, io, json, stat, tempfile, time, unittest
from contextlib import redirect_stdout
from pathlib import Path
from harness.minify.lib import events as E, unsafe as U

SPEC = Path("harness/minify/bin/minify-harness").resolve()

def load_cli():
    spec = importlib.util.spec_from_loader("mh_cli", importlib.machinery.SourceFileLoader("mh_cli", str(SPEC)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class TestCLI(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self.tmp.name) / "home")
        self.cwd = str(Path(self.tmp.name) / "proj")
        Path(self.cwd).mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()

    def measure(self, session, file, turn, tok_min, tok_fmt):
        E.append(self.cwd, session, {"k": "measure", "turn": turn, "file": file,
                                     "ext": file.rsplit(".", 1)[1], "tok_min": tok_min,
                                     "tok_fmt": tok_fmt, "chars_min": tok_min * 3,
                                     "chars_fmt": tok_fmt * 3, "formatter_ok": True,
                                     "style": "minified"}, home=self.home)

    def execute(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.cli.main(list(argv), home=self.home, cwd=self.cwd)
        return rc, buf.getvalue()

    def test_report_defaults_to_the_latest_session(self):
        self.measure("s1", "a.ts", 1, 10, 20)
        time.sleep(0.01)
        self.measure("s2", "b.ts", 1, 30, 60)
        rc, out = self.execute("report")
        self.assertEqual(rc, 0)
        self.assertIn("b.ts", out)
        self.assertNotIn("a.ts", out)

    def test_report_all_spans_sessions(self):
        self.measure("s1", "a.ts", 1, 10, 20)
        time.sleep(0.01)
        self.measure("s2", "b.ts", 1, 30, 60)
        _, out = self.execute("report", "--all")
        self.assertIn("a.ts", out)
        self.assertIn("b.ts", out)

    def test_report_by_lang(self):
        self.measure("s1", "a.ts", 1, 70, 100)
        self.measure("s1", "b.css", 1, 50, 100)
        _, out = self.execute("report", "--by-lang")
        self.assertIn("css", out)
        self.assertIn("ts", out)

    def test_report_with_no_data(self):
        rc, out = self.execute("report")
        self.assertEqual(rc, 0)
        self.assertIn("no measurements", out.lower())

    def test_doctor_prints_safe_and_blocked(self):
        rc, out = self.execute("doctor")
        self.assertEqual(rc, 0)
        self.assertIn("minify-safe", out.lower())
        self.assertIn("py", out)

    def test_doctor_clear_removes_an_entry(self):
        U.mark(self.cwd, "py", "no formatter", home=self.home)
        rc, out = self.execute("doctor", "--clear", "py")
        self.assertEqual(rc, 0)
        self.assertEqual(U.load(self.cwd, home=self.home), set())
        self.assertIn("cleared", out.lower())

    def test_doctor_clear_missing_returns_one(self):
        rc, out = self.execute("doctor", "--clear", "py")
        self.assertEqual(rc, 1)

if __name__ == "__main__":
    unittest.main()
