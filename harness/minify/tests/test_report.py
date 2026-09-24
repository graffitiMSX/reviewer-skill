import json, tempfile, unittest
from pathlib import Path
from harness.minify.lib.report import by_lang, dedupe, measures, render

def row(file, turn, tok_min, tok_fmt, ok=True, session="s1", ext=None):
    return {"k": "measure", "session": session, "turn": turn, "file": file,
            "ext": ext or file.rsplit(".", 1)[1], "tok_min": tok_min, "tok_fmt": tok_fmt,
            "chars_min": tok_min * 3, "chars_fmt": tok_fmt * 3 if tok_fmt else None,
            "formatter_ok": ok, "style": "minified"}

def churn_row(file, turn, tok_min, tok_fmt, churn_outside, lines_fmt, **kw):
    r = row(file, turn, tok_min, tok_fmt, **kw)
    r["churn_outside"] = churn_outside
    r["lines_fmt"] = lines_fmt
    return r

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

    def test_row_missing_file_is_skipped(self):
        rows = [row("a.ts", 1, 100, 150)]
        malformed = {"k": "measure", "session": "s1", "turn": 1, "tok_min": 100, "tok_fmt": 150,
                     "ext": "ts", "chars_min": 300, "chars_fmt": 450, "formatter_ok": True, "style": "minified"}
        # malformed row has no "file" field
        result = dedupe([malformed, *rows])
        self.assertEqual([r["file"] for r in result], ["a.ts"])

    def test_row_missing_tok_min_is_skipped(self):
        rows = [row("a.ts", 1, 100, 150)]
        malformed = {"k": "measure", "session": "s1", "turn": 1, "file": "b.ts", "tok_fmt": 150,
                     "ext": "ts", "chars_min": 300, "chars_fmt": 450, "formatter_ok": True, "style": "minified"}
        # malformed row has no "tok_min" field
        result = dedupe([malformed, *rows])
        self.assertEqual([r["file"] for r in result], ["a.ts"])

    def test_row_missing_ext_is_skipped(self):
        rows = [row("a.ts", 1, 100, 150)]
        malformed = {"k": "measure", "session": "s1", "turn": 1, "file": "b.ts", "tok_min": 100, "tok_fmt": 150,
                     "chars_min": 300, "chars_fmt": 450, "formatter_ok": True, "style": "minified"}
        # malformed row has no "ext" field
        result = dedupe([malformed, *rows])
        self.assertEqual([r["file"] for r in result], ["a.ts"])

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

    def test_turns_total_is_deduped_not_summed_per_row(self):
        """FIX 5: --turns must list every row (asserted by test_turns_flag_keeps_
        every_row above) but the TOTAL and the SAVED% headline must come from
        dedupe(rows), not from summing every row -- a file touched in turns 1 and 7
        would otherwise have its tokens counted twice. Worked example from the fix
        report: rows (100,150) and (200,320) must total 200/320 (38%), not the
        double-counted 300/470 (36%)."""
        rows = [row("a.ts", 1, 100, 150), row("a.ts", 7, 200, 320)]
        out = render(rows, scope="X", turns=True)
        self.assertIn("200", out)
        self.assertIn("320", out)
        self.assertIn("38%", out)      # 120/320 saved, half-up rounded
        self.assertNotIn("300", out)   # old, wrong double-counted tok_min total
        self.assertNotIn("470", out)   # old, wrong double-counted tok_fmt total

    def test_churn_heavy_row_is_excluded_from_total_but_shown_in_listing(self):
        """FIX 6: a row whose formatting rewrote far more than the session emitted
        (e.g. a one-character edit to a committed minified bundle, tok_min 1000 ->
        tok_fmt 40000) must not inflate the headline SAVED% -- it is excluded from
        the total but still listed and marked, so it stays visible rather than
        silently dropped."""
        heavy = churn_row("dist/bundle.js", 1, 1000, 40000, churn_outside=3990, lines_fmt=4000)
        clean = row("src/api.ts", 1, 100, 150)
        out = render([heavy, clean], scope="X")
        self.assertIn("dist/bundle.js", out)             # still listed
        self.assertIn("src/api.ts", out)
        self.assertIn("churn", out.lower())               # marked inline
        # total reflects only the clean row
        lines = out.splitlines()
        total_line = next(l for l in lines if l.strip().startswith("total"))
        self.assertIn("100", total_line)
        self.assertIn("150", total_line)
        self.assertNotIn("1000", total_line)
        self.assertNotIn("41000", out)  # 1000+40000, the wrong inflated total
        self.assertIn("SAVED 33%", out)  # 50/150, only the clean row

    def test_all_rows_churn_heavy_reports_no_measurements_in_total(self):
        heavy = churn_row("dist/bundle.js", 1, 1000, 40000, churn_outside=3990, lines_fmt=4000)
        out = render([heavy], scope="X")
        self.assertIn("dist/bundle.js", out)
        total_line = next(l for l in out.splitlines() if l.strip().startswith("total"))
        self.assertIn("0", total_line)
        self.assertIn("SAVED -", out)  # _pct with base 0 renders "-"

    def test_render_with_all_malformed_rows_shows_empty_message(self):
        malformed = [
            {"k": "measure", "session": "s1", "turn": 1, "tok_min": 100, "tok_fmt": 150,
             "ext": "ts", "formatter_ok": True},  # missing file
            {"k": "measure", "session": "s1", "turn": 1, "file": "a.ts", "tok_fmt": 150,
             "ext": "ts", "formatter_ok": True},  # missing tok_min
        ]
        out = render(malformed, scope="TEST")
        self.assertIn("no measurements", out.lower())

    def test_render_with_mixed_rows_skips_malformed_ones(self):
        good = row("a.ts", 1, 100, 150)
        malformed = {"k": "measure", "session": "s1", "turn": 1, "file": "b.ts",
                     "tok_fmt": 100, "ext": "ts", "formatter_ok": True}  # missing tok_min
        out = render([malformed, good], scope="TEST")
        self.assertIn("a.ts", out)
        self.assertNotIn("b.ts", out)

class TestByLang(unittest.TestCase):
    def test_groups_and_sorts_by_saving(self):
        rows = [row("a.ts", 1, 70, 100), row("b.ts", 1, 70, 100), row("c.css", 1, 50, 100)]
        got = by_lang(dedupe(rows))
        self.assertEqual([g["ext"] for g in got], ["css", "ts"])   # css saves 50%, ts saves 30%
        self.assertEqual(got[1]["tok_min"], 140)

    def test_by_lang_filters_malformed_rows(self):
        good = row("a.ts", 1, 100, 150)
        malformed = {"k": "measure", "session": "s1", "turn": 1, "file": "b.ts", "tok_fmt": 100,
                     "ext": "ts", "formatter_ok": True}  # missing tok_min
        got = by_lang([good, malformed])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["files"], 1)
        self.assertEqual(got[0]["tok_min"], 100)

    def test_by_lang_with_zero_tok_fmt_sum(self):
        rows = [row("a.ts", 1, 100, 0)]
        got = by_lang(rows)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["tok_fmt"], 0)
        self.assertEqual(got[0]["saved"], -100)

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
