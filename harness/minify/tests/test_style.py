import re, unittest
from pathlib import Path
from harness.minify.lib.classes import COLLAPSE, DENSE
from harness.minify.lib.doctor import one_line

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

    def test_all_four_verdict_renderings_are_quoted(self):
        """Check that the style quotes all four verdicts produced by one_line()."""
        text = STYLE.read_text()

        # Generate all four verdict renderings from doctor.one_line()
        verdicts = [
            {"repo_clean": True, "safe": [], "blocked": [], "checked": 0, "tracked_total": 0, "truncated": False},
            {"repo_clean": False, "safe": [], "blocked": [], "checked": 0, "tracked_total": 0, "truncated": False},
            {"repo_clean": None, "safe": [], "blocked": [], "checked": 200, "tracked_total": 912, "truncated": True},
            {"repo_clean": None, "safe": [], "blocked": [], "checked": 0, "tracked_total": 0, "truncated": False},
        ]

        for verdict in verdicts:
            line = one_line(verdict)
            # Extract just the rule part (after the last |)
            rule = line.split(" | ")[-1]
            # For the sampled case, check that the pattern is present (N and M will vary)
            if "checked" in rule:
                self.assertIn("checked", text, f"Style should mention 'checked' for sampled verdicts")
                self.assertIn("cleanliness unknown:", text, f"Style should quote the 'cleanliness unknown:' token")
            else:
                # For non-sampled verdicts, check the exact rule string
                self.assertIn(rule, text, f"Style should quote verdict: {rule}")

if __name__ == "__main__":
    unittest.main()
