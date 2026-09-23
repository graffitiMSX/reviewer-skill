import json, tempfile, unittest
from pathlib import Path
from harness.minify.lib.estimate import estimate, chars, load_k

class TestEstimate(unittest.TestCase):
    def test_word_runs(self):
        self.assertEqual(estimate("ab"), 1)        # 2/4.2 -> 1 (floor of 1)
        self.assertEqual(estimate("abcd"), 1)      # 0.95 -> 1
        self.assertEqual(estimate("abcdefgh"), 2)  # 1.90 -> 2

    def test_digit_run(self):
        self.assertEqual(estimate("12345"), 2)     # 1.67 -> 2

    def test_newline_is_one_token(self):
        self.assertEqual(estimate("\n"), 1)
        self.assertEqual(estimate("\n\n\n"), 3)

    def test_whitespace_run(self):
        self.assertEqual(estimate("    "), 1)      # 0.67 -> 1 via the floor

    def test_punctuation_runs(self):
        self.assertEqual(estimate("=>"), 1)        # 1.25 -> 1
        self.assertEqual(estimate("();=>{}"), 4)   # 4.375 -> 4

    def test_composite_line(self):
        # "const"=1 " "=1 "a"=1 "="=1 "1"=1 ";"=1 "\n"=1
        self.assertEqual(estimate("const a=1;\n"), 7)

    def test_empty(self):
        self.assertEqual(estimate(""), 0)
        self.assertEqual(chars(""), 0)

    def test_chars_counts_utf8_bytes(self):
        self.assertEqual(chars("abc"), 3)
        self.assertEqual(chars("café"), 5)

    def test_k_scales_the_total(self):
        self.assertEqual(estimate("const a=1;\n", k=2.0), 14)

    def test_ratio_is_stable_under_k(self):
        a = "const alpha=1;\n" * 40
        b = "const alpha = 1;\n\n" * 40
        r1 = estimate(a) / estimate(b)
        r2 = estimate(a, k=1.31) / estimate(b, k=1.31)
        self.assertLess(abs(r1 - r2) / r1, 0.02)

    def test_load_k_defaults_to_uncalibrated(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "missing.json"
            self.assertEqual(load_k(str(p)), (1.0, False))

    def test_load_k_reads_calibrated_value(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "calibration.json"
            p.write_text(json.dumps({"k": 1.07, "calibrated": True}))
            self.assertEqual(load_k(str(p)), (1.07, True))

    def test_load_k_with_json_list(self):
        """Finding 1: malformed JSON shape (list instead of dict) should not raise."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "calibration.json"
            p.write_text(json.dumps([1, 2, 3]))
            self.assertEqual(load_k(str(p)), (1.0, False))

    def test_load_k_with_null_k(self):
        """Finding 1: null k value should not raise TypeError."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "calibration.json"
            p.write_text(json.dumps({"k": None, "calibrated": True}))
            self.assertEqual(load_k(str(p)), (1.0, False))

    def test_load_k_with_invalid_json_syntax(self):
        """Finding 1: syntactically invalid JSON should not raise."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "calibration.json"
            p.write_text("{not valid json")
            self.assertEqual(load_k(str(p)), (1.0, False))

    def test_unicode_word_stays_one_run(self):
        """Finding 2: Unicode word characters should be one run, not split on accents."""
        self.assertEqual(estimate("café"), 1)
        self.assertEqual(estimate("cafe"), 1)

    def test_crlf_is_one_newline(self):
        """Finding 2: CRLF should be counted as exactly one newline token."""
        self.assertEqual(estimate("\r\n"), 1)
        self.assertEqual(estimate("\r\n\r\n\r\n"), 3)

    def test_lone_carriage_return(self):
        """Finding 2: lone CR should not be silently dropped; counted as whitespace."""
        self.assertEqual(estimate("\r"), 1)

    def test_goldens_after_unicode_fix(self):
        """Finding 2: re-assert goldens after regex and newline changes."""
        self.assertEqual(estimate("const a=1;\n"), 7)
        self.assertEqual(estimate("const a = 1;\n"), 9)

if __name__ == "__main__":
    unittest.main()
