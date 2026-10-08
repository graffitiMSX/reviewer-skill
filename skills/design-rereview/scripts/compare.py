#!/usr/bin/env python3
"""Compare a design re-review with its baseline review.

Usage:
  compare.py --baseline docs/remediation/design-review.md --current docs/remediation/rereview-2026-10-08
  compare.py --baseline <folder of design-review-<lens>.md> --current <folder of design-rereview-<lens>.md>

The baseline is either the merged report (split on its `# Lens: <name>` headings)
or a folder of per-lens files. The current folder holds one re-review file per
lens, in the format of references/rereview-format.md.

It recomputes both sides with the design-review rules (aspect caps, lens score,
overall score) and prints the comparison section for the merged re-review.
Baseline grades come from the baseline's own scorecard when it has one, and
otherwise from the re-review's "Baseline grades" table, labelled reconstructed.

Exit status is 1 when a baseline finding has no status, a current grade breaks
its cap, or a table is missing. The comparison is still printed.
"""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SCORECARD_DIR = HERE.parents[2] / "design-review" / "scripts"
sys.path.insert(0, str(SCORECARD_DIR))
try:
    import scorecard as sc
except ImportError:
    sys.exit(f"error: cannot import scorecard.py from {SCORECARD_DIR}; the design-review skill must sit next to this one")

LENSES = sc.LENSES
ALIASES = {"front-end": "frontend", "front end": "frontend", "arch": "architecture", "sec": "security"}
STATUSES = ["Fixed", "Partially fixed", "Open", "Regressed", "Accepted", "Not verifiable"]
LENS_HEADING = re.compile(r"^# Lens:\s*(.+?)\s*$", re.M)
BASELINE_HEADER = re.compile(r"^\|\s*Aspect\s*\|\s*Baseline grade\s*\|", re.I)
STATUS_HEADER = re.compile(r"^\|\s*Finding\s*\|\s*Severity\s*\|\s*Status\s*\|", re.I)


def norm_lens(name):
    name = name.strip().lower().split("—")[0].split(" - ")[0].strip()
    return ALIASES.get(name, name)


def load_lenses(path, prefix):
    """lens name -> text, from a merged file or a folder of <prefix>-<lens>.md files."""
    path = Path(path)
    if path.is_dir():
        return {l: (path / f"{prefix}-{l}.md").read_text(encoding="utf-8")
                for l in LENSES if (path / f"{prefix}-{l}.md").exists()}
    text = path.read_text(encoding="utf-8")
    marks = list(LENS_HEADING.finditer(text))
    if not marks:
        return {sc.lens_name(path, text): text}
    out = {}
    for i, m in enumerate(marks):
        name = norm_lens(m.group(1))
        chunk = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        # A merged report can repeat a lens heading (the skill's own, then the lens file's title).
        # Keep the chunk that holds the content.
        if name in LENSES and len(chunk) > len(out.get(name, "")):
            out[name] = chunk
    return out


def table_rows(text, header):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if header.match(line):
            rows = []
            for row in lines[i + 2:]:
                if not row.strip().startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip().strip("|").split("|")])
            return rows
    return None


def parse_grade(cell):
    raw = cell.lower().strip("* `")
    m = re.match(r"^(\d+(?:\.\d+)?)", raw)
    return float(m.group(1)) if m else None


def key(aspect):
    return re.sub(r"[^a-z0-9]+", " ", aspect.lower()).strip()


def lens_score(grades, findings):
    graded = [g for g in grades.values() if g is not None]
    if not graded:
        return None
    mean = sc.one_decimal(sum(graded) / len(graded))
    cap, _ = sc.worst_firm(findings)
    return min(mean, cap)


def overall(scores, findings):
    vals = [s for s in scores.values() if s is not None]
    if not vals:
        return None
    mean = sc.one_decimal(sum(vals) / len(vals))
    cap, _ = sc.worst_firm(findings)
    return min(mean, cap)


def change(before, after):
    if before is None or after is None:
        return "—"
    d = sc.one_decimal(after - before)
    return "=" if d == 0 else (f"▲ +{d:g}" if d > 0 else f"▼ {d:g}")


def fmt(v, decimal=True):
    if v is None:
        return "—"
    return f"{v:.1f}" if decimal else f"{v:g}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--current", required=True)
    args = ap.parse_args()

    base_texts = load_lenses(args.baseline, "design-review")
    cur_texts = load_lenses(args.current, "design-rereview")
    if not cur_texts:
        sys.exit(f"error: no design-rereview-<lens>.md files in {args.current}")

    problems, rows_lens, rows_aspect, status_rows = [], [], [], []
    base_scores, cur_scores, base_all, cur_all = {}, {}, {}, {}
    reconstructed = False

    for lens in [l for l in LENSES if l in cur_texts]:
        cur = cur_texts[lens]
        base = base_texts.get(lens)
        if base is None:
            problems.append(f"{lens}: no baseline section for this lens, so it cannot be compared")
            continue
        base_findings = sc.parse_findings(base)
        cur_findings = sc.parse_findings(cur)
        base_all.update(base_findings)
        cur_all.update(cur_findings)

        # current grades, with cap checks
        card = sc.parse_scorecard(cur)
        cur_grades, names = {}, {}
        if card is None:
            problems.append(f"{lens}: no current scorecard table (`| Aspect | Grade | ...`)")
        else:
            for aspect, grade, state, ids, reason in card:
                names[key(aspect)] = aspect
                cur_grades[key(aspect)] = grade
                if grade is None:
                    continue
                cap, source = sc.aspect_cap(ids, cur_findings)
                if grade > cap:
                    problems.append(f"{lens} / {aspect}: current grade {grade:g} exceeds its cap of {cap} ({source})")
                if not reason:
                    problems.append(f"{lens} / {aspect}: no reason given for the current grade")
                for fid in ids:
                    if fid not in cur_findings:
                        problems.append(f"{lens} / {aspect}: cites {fid}, which has no heading under open or new findings")

        # baseline grades: the baseline's own scorecard, else the reconstructed table
        base_grades, source = {}, "scorecard"
        base_card = sc.parse_scorecard(base)
        if base_card is not None:
            for aspect, grade, _, _, _ in base_card:
                names.setdefault(key(aspect), aspect)
                base_grades[key(aspect)] = grade
        else:
            source = "reconstructed"
            reconstructed = True
            rows = table_rows(cur, BASELINE_HEADER)
            if rows is None:
                problems.append(f"{lens}: the baseline has no scorecard and the re-review has no `| Aspect | Baseline grade | Source |` table")
            else:
                for cells in rows:
                    if len(cells) >= 2:
                        names.setdefault(key(cells[0]), cells[0].strip("* "))
                        base_grades[key(cells[0])] = parse_grade(cells[1])

        # every baseline finding needs exactly one status
        rows = table_rows(cur, STATUS_HEADER)
        counts = {s: 0 for s in STATUSES}
        if rows is None:
            problems.append(f"{lens}: no finding status table (`| Finding | Severity | Status | ...`)")
        else:
            seen = {}
            for cells in rows:
                ids = sc.FINDING_ID.findall(cells[0]) if cells else []
                if not ids or len(cells) < 3:
                    continue
                fid = ids[0].upper()
                status = next((s for s in STATUSES if cells[2].strip("* ").lower().startswith(s.lower())), None)
                if status is None:
                    problems.append(f"{lens} / {fid}: unknown status '{cells[2]}'")
                    continue
                if fid in seen:
                    problems.append(f"{lens} / {fid}: listed twice in the status table")
                seen[fid] = status
                if fid in base_findings:
                    counts[status] += 1
                if status != "Fixed" and fid not in cur_findings:
                    problems.append(f"{lens} / {fid}: status {status}, but it has no heading under open findings, so it cannot cap a grade")
                if status == "Fixed" and fid in cur_findings:
                    problems.append(f"{lens} / {fid}: marked Fixed but still listed under open findings")
            for fid in sorted(base_findings):
                if fid not in seen:
                    problems.append(f"{lens} / {fid}: baseline finding has no status")
        new = sorted(f for f in cur_findings if f not in base_findings)
        status_rows.append((lens, len(base_findings), counts, len(new)))

        b, c = lens_score(base_grades, base_findings), lens_score(cur_grades, cur_findings)
        base_scores[lens], cur_scores[lens] = b, c
        rows_lens.append((lens, b, c, source))
        for k in list(dict.fromkeys(list(base_grades) + list(cur_grades))):
            rows_aspect.append((lens, names.get(k, k), base_grades.get(k), cur_grades.get(k)))

    print("## Score comparison\n")
    b, c = overall(base_scores, base_all), overall(cur_scores, cur_all)
    if b is not None and c is not None:
        print(f"**Overall: {b:.1f} → {c:.1f} ({change(b, c)})**\n")
        print(f"- Before: {sc.gauge(b)} — {sc.label(b)}")
        print(f"- Now: {sc.gauge(c)} — {sc.label(c)}\n")
    compared = [l for l, _, _, _ in rows_lens]
    notes = []
    if len(compared) < len(LENSES):
        notes.append(f"Partial comparison: {', '.join(compared)} only.")
    if reconstructed:
        notes.append("Baseline grades marked reconstructed were derived from the baseline findings with the same rubric, because that review predates grading.")
    bc, bs = sc.worst_firm(base_all)
    cc, cs = sc.worst_firm(cur_all)
    notes.append(f"Caps: before {'none' if bs is None else f'{bc} ({bs} open)'}, now {'none' if cs is None else f'{cc} ({cs} open)'}.")
    print(" ".join(notes) + "\n")

    print("| Lens | Before | Now | Change | Gauge now | Baseline grades |")
    print("|---|---|---|---|---|---|")
    for lens, bv, cv, source in rows_lens:
        print(f"| {lens} | {fmt(bv)} | {fmt(cv)} | {change(bv, cv)} | {sc.gauge(cv) if cv is not None else '—'} | {source} |")

    print("\n### Every aspect, biggest gain first\n")
    print("| Lens | Aspect | Before | Now | Change |")
    print("|---|---|---|---|---|")
    def gain(r):
        return -(r[3] - r[2]) if r[2] is not None and r[3] is not None else 99
    for lens, aspect, bv, cv in sorted(rows_aspect, key=lambda r: (gain(r), r[0], r[1])):
        print(f"| {lens} | {aspect} | {fmt(bv, False)} | {fmt(cv, False)} | {change(bv, cv)} |")

    print("\n### Baseline findings by status\n")
    print("| Lens | Baseline findings | " + " | ".join(STATUSES) + " | New since |")
    print("|---|---|" + "---|" * (len(STATUSES) + 1))
    tot = {s: 0 for s in STATUSES}
    tb = tn = 0
    for lens, nb, counts, nnew in status_rows:
        print(f"| {lens} | {nb} | " + " | ".join(str(counts[s]) for s in STATUSES) + f" | {nnew} |")
        for s in STATUSES:
            tot[s] += counts[s]
        tb, tn = tb + nb, tn + nnew
    if len(status_rows) > 1:
        print(f"| **total** | {tb} | " + " | ".join(str(tot[s]) for s in STATUSES) + f" | {tn} |")

    if problems:
        print("\n### Problems to fix before publishing\n")
        for p in problems:
            print(f"- {p}")
        sys.exit(1)


if __name__ == "__main__":
    main()
