import ast, json, subprocess, tempfile, unittest
from pathlib import Path
from harness.minify.lib.detect import detect

F = Path("harness/minify/tests/fixtures/pairs")

def prettier():
    """The repo's own prettier, or None. TS/CSS proofs need a real formatter."""
    return detect(str(Path.cwd()), "ts")

def fmt_with(tool, text, suffix):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"f{suffix}"
        p.write_text(text)
        ok, err = tool.format(str(p))
        return (p.read_text() if ok else None), err

class TestNoDependencyProofs(unittest.TestCase):
    """These always run: ast and json prove equivalence with no formatter at all."""

    def test_python_pair_is_semantically_identical(self):
        a = ast.dump(ast.parse((F / "sync.readable.py").read_text()))
        b = ast.dump(ast.parse((F / "sync.min.py").read_text()))
        self.assertEqual(a, b)

    def test_dense_python_still_parses(self):
        ast.parse((F / "sync.min.py").read_text())

    def test_json_pair_is_identical(self):
        a = json.loads((F / "config.readable.json").read_text())
        b = json.loads((F / "config.min.json").read_text())
        self.assertEqual(a, b)

    def test_asi_collapse_is_not_valid_javascript_shape(self):
        # No JS parser in the stdlib, so assert the hazard textually: the collapsed
        # form joined two statements with no separator between them.
        collapsed = (F / "asi.collapsed.js").read_text()
        self.assertIn("const x=a const y=b", collapsed)
        self.assertNotIn(";", collapsed.split("{", 1)[1].split("}")[0])

class TestFormatterProofs(unittest.TestCase):
    """Skipped when the project has no prettier: TS and CSS need a real parser."""

    def setUp(self):
        self.tool = prettier()
        if self.tool is None or not self.tool.per_file:
            self.skipTest("no per-file prettier available in this project")

    def test_ts_minified_formats_successfully(self):
        """Formatting the minified version succeeds, proving the collapse did not break the language."""
        minified, _ = fmt_with(self.tool, (F / "api.min.ts").read_text(), ".ts")
        self.assertIsNotNone(minified, "minified TS must format cleanly")

    def test_ts_formatted_matches_golden(self):
        """Formatting the minified version produces the expected golden result."""
        minified, _ = fmt_with(self.tool, (F / "api.min.ts").read_text(), ".ts")
        golden = (F / "api.formatted.ts").read_text()
        self.assertEqual(minified, golden)

    def test_ts_golden_is_idempotent(self):
        """Formatting the golden again returns the golden unchanged."""
        golden = (F / "api.formatted.ts").read_text()
        reformatted, _ = fmt_with(self.tool, golden, ".ts")
        self.assertEqual(reformatted, golden)

    def test_css_minified_formats_successfully(self):
        """Formatting the minified version succeeds, proving the collapse did not break the language."""
        minified, _ = fmt_with(self.tool, (F / "card.min.css").read_text(), ".css")
        self.assertIsNotNone(minified, "minified CSS must format cleanly")

    def test_css_formatted_matches_golden(self):
        """Formatting the minified version produces the expected golden result."""
        minified, _ = fmt_with(self.tool, (F / "card.min.css").read_text(), ".css")
        golden = (F / "card.formatted.css").read_text()
        self.assertEqual(minified, golden)

    def test_css_golden_is_idempotent(self):
        """Formatting the golden again returns the golden unchanged."""
        golden = (F / "card.formatted.css").read_text()
        reformatted, _ = fmt_with(self.tool, golden, ".css")
        self.assertEqual(reformatted, golden)

    def test_asi_collapsed_js_fails_to_format(self):
        out, err = fmt_with(self.tool, (F / "asi.collapsed.js").read_text(), ".js")
        self.assertIsNone(out, "naive ASI collapsing must not format cleanly")

if __name__ == "__main__":
    unittest.main()
