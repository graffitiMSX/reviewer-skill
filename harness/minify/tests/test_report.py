import json, tempfile, unittest
from pathlib import Path
from harness.minify.lib.report import by_lang, dedupe, measures, render

def row(file, turn, tok_min, tok_fmt, ok=True, session="s1", ext=None):
    return {"k": "measure", "session": session, "turn": turn, "file": file,
            "ext": ext or file.rsplit(".", 1)[1], "tok_min": tok_min, "tok_fmt": tok_fmt,
            "chars_min": tok_min * 3, "chars_fmt": tok_fmt * 3 if tok_fmt else None,
            "formatter_ok": ok, "style": "minified"}

class TestDedupe(unittest.TestCase):
    def test_last_turn_per_file_wins(self):
        rows = [row("a.ts", 1, 100, 150), row("a.ts", 7, 200, 320), row("b.css", 2, 10, 20)]
        self.assertEqual([(r["file"], r["turn"]) for r in dedupe(rows)], [("a.ts", 7), ("b.css", 2)])

    def test_same_file_in_two_sessions_is_two_rows(self):
        rows = [row("a.ts", 1, 100, 150, session="s1"), row("a.ts", 1, 100, 150, session="s2")]
        self.assertEqual(len(dedupe(rows)), 2)

    def test_unformatted_rows_are_dropped(self):
        rows = [row("a.ts", 1, 100, None, ok=False), row("b.ts", 1, 10, 20)]
        self.assertEqual([r["file"] for r in dedupe(rows)], ["b.ts"])

class TestRender(unittest.TestCase):
    def test_totals_and_percentage(self):
        out = render([row("src/api.ts", 1, 412, 631), row("src/card.css", 1, 88, 142)], scope="SESSION s1")
        self.assertIn("src/api.ts", out)
        self.assertIn("500", out)          # tok_min total
        self.assertIn("773", out)          # tok_fmt total
        self.assertIn("273", out)          # saved
        self.assertIn("35%", out)          # 273/773
        self.assertIn("SESSION s1", out)

    def test_empty_report_says_so(self):
        self.assertIn("no measurements", render([], scope="SESSION s1").lower())

    def test_chars_flag_adds_byte_counts(self):
        out = render([row("a.ts", 1, 100, 200)], scope="X", chars=True)
        self.assertIn("chars", out.lower())

    def test_turns_flag_keeps_every_row(self):
        rows = [row("a.ts", 1, 100, 150), row("a.ts", 7, 200, 320)]
        self.assertEqual(render(rows, scope="X", turns=True).count("a.ts"), 2)
        self.assertEqual(render(rows, scope="X").count("a.ts"), 1)

    def test_uncalibrated_estimator_is_labelled(self):
        self.assertIn("uncalibrated", render([row("a.ts", 1, 1, 2)], scope="X").lower())

class TestByLang(unittest.TestCase):
    def test_groups_and_sorts_by_saving(self):
        rows = [row("a.ts", 1, 70, 100), row("b.ts", 1, 70, 100), row("c.css", 1, 50, 100)]
        got = by_lang(dedupe(rows))
        self.assertEqual([g["ext"] for g in got], ["css", "ts"])   # css saves 50%, ts saves 30%
        self.assertEqual(got[1]["tok_min"], 140)

class TestMeasures(unittest.TestCase):
    def test_reads_only_measure_rows_and_tags_the_session(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sess-abc.ndjson"
            p.write_text(json.dumps({"k": "write", "file": "a.ts"}) + "\n"
                         + json.dumps({"k": "measure", "file": "a.ts", "turn": 1,
                                       "tok_min": 1, "tok_fmt": 2, "formatter_ok": True,
                                       "ext": "ts"}) + "\n")
            rows = measures([p])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["session"], "sess-abc")

if __name__ == "__main__":
    unittest.main()
