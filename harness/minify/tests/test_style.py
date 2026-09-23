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
        """Check that the style quotes all four verdicts produced by one_line().

        This test ensures the style document contains the exact rule strings that
        doctor.one_line() produces, so an assistant can match tokens against hook
        output. The test derives all strings from one_line() without hardcoding,
        and verifies the plain unknown form appears at least twice (standalone and
        as tail of sampled form) to guard against accidental deletion.
        """
        text = STYLE.read_text()

        # Normalize whitespace in the style: collapse all runs to single spaces.
        # This handles the sampled rendering which wraps across physical lines.
        text_normalized = " ".join(text.split())

        # Generate all four verdict renderings from doctor.one_line()
        verdicts = [
            {"repo_clean": True, "safe": [], "blocked": [], "checked": 0, "tracked_total": 0, "truncated": False},
            {"repo_clean": False, "safe": [], "blocked": [], "checked": 0, "tracked_total": 0, "truncated": False},
            {"repo_clean": None, "safe": [], "blocked": [], "checked": 200, "tracked_total": 912, "truncated": True},
            {"repo_clean": None, "safe": [], "blocked": [], "checked": 0, "tracked_total": 0, "truncated": False},
        ]

        # Extract all four rules from one_line() without branching or hardcoding
        rules = []
        for verdict in verdicts:
            line = one_line(verdict)
            rule = line.split(" | ")[-1]
            rules.append(rule)

        # Normalize numeric placeholder: replace actual numbers with fixed token.
        # The hook emits "checked 200 of 912," and the style writes "checked N of M,".
        # We normalize both to "checked N of M," so they match after normalization.
        def normalize_checked(s):
            return re.sub(r"checked \d+ of \d+,", "checked N of M,", s)

        rules_normalized = [normalize_checked(r) for r in rules]
        text_normalized = normalize_checked(text_normalized)

        # Verify each rule is in the normalized text, without hardcoding literals
        for i, rule_norm in enumerate(rules_normalized, 1):
            self.assertIn(rule_norm, text_normalized,
                f"Rule {i} not found in style: {rule_norm}")

        # The plain unknown form (rules[3]) must appear at least twice:
        # once as a standalone line and once as the tail of the sampled form.
        # If someone deletes the standalone line, the count drops to 1 and this fails.
        plain_unknown = rules_normalized[3]
        count = text_normalized.count(plain_unknown)
        self.assertGreaterEqual(count, 2,
            f"Plain unknown verdict must appear at least twice (standalone + sampled tail), "
            f"but found {count} occurrences: {plain_unknown}")

if __name__ == "__main__":
    unittest.main()
