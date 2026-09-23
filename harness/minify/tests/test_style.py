import re, unittest
from pathlib import Path
from harness.minify.lib.classes import COLLAPSE, DENSE

STYLE = Path("harness/minify/output-styles/minified.md")

def listed(label):
    text = STYLE.read_text()
    m = re.search(rf"^<!-- {label}: (.+) -->$", text, re.M)
    return frozenset(m.group(1).split()) if m else frozenset()

class TestStyle(unittest.TestCase):
    def test_file_exists_with_frontmatter(self):
        text = STYLE.read_text()
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: minified", text)
        self.assertIn("description:", text)

    def test_collapse_list_matches_classes_module(self):
        self.assertEqual(listed("collapse"), COLLAPSE)

    def test_dense_list_matches_classes_module(self):
        self.assertEqual(listed("dense"), DENSE)

    def test_states_the_asi_rule(self):
        self.assertIn("semicolon insertion", STYLE.read_text())

    def test_states_the_minread_constraint(self):
        self.assertIn("minread", STYLE.read_text())

    def test_tells_the_model_to_respect_the_session_verdict(self):
        self.assertIn("minify-harness:", STYLE.read_text())

if __name__ == "__main__":
    unittest.main()
