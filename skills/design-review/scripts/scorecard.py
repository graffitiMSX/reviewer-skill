#!/usr/bin/env python3
"""Compute the design-review scorecard from the lens reports.

Usage:
  scorecard.py docs/remediation                 # reads design-review-<lens>.md in that folder
  scorecard.py a.md b.md ...                    # or explicit lens files

Reviewers grade aspects, which is judgement. This script does the arithmetic,
which is not: it reads each lens report's scorecard table and its findings,
checks every grade against its cap, recomputes the lens scores and the overall
score, and prints the scorecard section for the merged report.

Rules (references/conventions.md):
  aspect cap   Confirmed/Likely Critical -> 3, High -> 6
               Needs-verification Critical -> 5, High -> 7
  lens score   mean of graded aspects, 1 decimal; <= 4.0 with a Confirmed/Likely
               Critical in the lens, <= 6.5 with a Confirmed/Likely High
  overall      mean of lens scores, 1 decimal, same two caps across all lenses

Exit status is 1 when a grade breaks its cap or a scorecard is missing, so the
skill's quality gate can rely on it. The scorecard is still printed.
"""
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

LENSES = ["architecture", "backend", "frontend", "ux", "security"]
FINDING = re.compile(r"^#{2,4}\s*(F-(?:ARC|BE|FE|UX|SEC)-\d+)\s*\[(Critical|High|Medium|Low|Informational)", re.M | re.I)
FINDING_ID = re.compile(r"F-(?:ARC|BE|FE|UX|SEC)-\d+")
CONFIDENCE = re.compile(r"\*\*Confidence\*\*\s*:?\s*([^\n·|]*)", re.I)
HEADER = re.compile(r"^\|\s*Aspect\s*\|\s*Grade\s*\|", re.I)


def one_decimal(value):
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def gauge(score):
    filled = int(Decimal(str(score)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    filled = max(0, min(10, filled))
    text = str(int(score)) if float(score).is_integer() and isinstance(score, int) else f"{score:.1f}"
    return "▰" * filled + "▱" * (10 - filled) + f" {text}/10"


def label(score):
    for floor, name in ((9, "Excellent"), (7, "Good"), (5, "Fair"), (3, "Poor")):
        if score >= floor:
            return name
    return "Critical"


def parse_findings(text):
    """finding id -> (severity, firm) where firm is False for Needs-verification only."""
    found = {}
    marks = list(FINDING.finditer(text))
    for i, m in enumerate(marks):
        block = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        conf = CONFIDENCE.search(block)
        conf_text = conf.group(1).lower() if conf else ""
        firm = not ("needs verification" in conf_text and "confirmed" not in conf_text and "likely" not in conf_text)
        found.setdefault(m.group(1).upper(), (m.group(2).capitalize(), firm))
    return found


def parse_scorecard(text):
    """rows of (aspect, grade or None, state, finding ids, reason)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not HEADER.match(line):
            continue
        cols = [c.strip().lower() for c in line.strip().strip("|").split("|")]
        idx = {name: cols.index(name) for name in ("aspect", "grade") if name in cols}
        why = cols.index("why") if "why" in cols else None
        rows = []
        for row in lines[i + 2:]:
            if not row.strip().startswith("|"):
                break
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) <= max(idx.values()):
                continue
            raw = cells[idx["grade"]].lower().strip("* `")
            num = re.match(r"^(\d+(?:\.\d+)?)", raw)
            if num:
                grade, state = float(num.group(1)), "graded"
            elif "assess" in raw:
                grade, state = None, "not assessed"
            else:
                grade, state = None, "n/a"
            ids = sorted(set(i.upper() for i in FINDING_ID.findall(row)))
            reason = cells[why] if why is not None and why < len(cells) else ""
            rows.append((cells[idx["aspect"]].strip("* "), grade, state, ids, reason))
        return rows
    return None


def aspect_cap(ids, findings):
    cap, source = 10, None
    for fid in ids:
        sev, firm = findings.get(fid, (None, True))
        limit = {("Critical", True): 3, ("High", True): 6, ("Critical", False): 5, ("High", False): 7}.get((sev, firm))
        if limit is not None and limit < cap:
            cap, source = limit, f"{fid}, {sev}{'' if firm else ', needs verification'}"
    return cap, source


def worst_firm(findings):
    sevs = {sev for sev, firm in findings.values() if firm}
    if "Critical" in sevs:
        return 4.0, "Critical"
    if "High" in sevs:
        return 6.5, "High"
    return 10.0, None


def lens_name(path, text):
    m = re.search(r"design-review-([a-z]+)\.md$", path.name)
    if m:
        return m.group(1)
    ids = FINDING_ID.findall(text)
    code = ids[0].split("-")[1] if ids else ""
    return {"ARC": "architecture", "BE": "backend", "FE": "frontend", "UX": "ux", "SEC": "security"}.get(code, path.stem)


def main(argv):
    if not argv:
        sys.exit(__doc__)
    paths = []
    for arg in argv:
        p = Path(arg)
        if p.is_dir():
            paths += [p / f"design-review-{l}.md" for l in LENSES if (p / f"design-review-{l}.md").exists()]
        else:
            paths.append(p)
    if not paths:
        sys.exit("error: no lens reports found")

    problems, lenses, all_aspects, all_findings = [], [], [], {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        name = lens_name(path, text)
        findings = parse_findings(text)
        all_findings.update(findings)
        rows = parse_scorecard(text)
        if rows is None:
            problems.append(f"{name}: no scorecard table (header `| Aspect | Grade | ...`)")
            continue
        graded = []
        for aspect, grade, state, ids, reason in rows:
            if state != "graded":
                all_aspects.append((name, aspect, None, state))
                continue
            if not 0 <= grade <= 10:
                problems.append(f"{name} / {aspect}: grade {grade:g} is outside 0-10")
                continue
            cap, source = aspect_cap(ids, findings)
            if grade > cap:
                problems.append(f"{name} / {aspect}: grade {grade:g} exceeds its cap of {cap} ({source})")
            if not reason:
                problems.append(f"{name} / {aspect}: no reason given for the grade")
            unknown = [i for i in ids if i not in findings]
            if unknown:
                problems.append(f"{name} / {aspect}: cites {', '.join(unknown)}, not found in this report")
            graded.append((aspect, grade, ids))
            all_aspects.append((name, aspect, grade, state))
        if not graded:
            problems.append(f"{name}: scorecard has no graded aspect")
            continue
        mean = one_decimal(sum(g for _, g, _ in graded) / len(graded))
        cap, sev = worst_firm(findings)
        score = min(mean, cap)
        weakest = min(graded, key=lambda r: r[1])
        note = f"mean of {len(graded)} aspects {mean:.1f}" + (f", capped at {cap} by a {sev} finding" if score < mean else "")
        lenses.append((name, score, note, weakest))

    print("## Scorecard\n")
    if lenses:
        mean = one_decimal(sum(s for _, s, _, _ in lenses) / len(lenses))
        cap, sev = worst_firm(all_findings)
        overall = min(mean, cap)
        names = ", ".join(n for n, _, _, _ in lenses)
        partial = "" if len(lenses) == len(LENSES) else f" Partial score: {names} only."
        capped = f", capped at {cap} by a {sev} finding" if overall < mean else ""
        print(f"**Overall: {gauge(overall)} — {label(overall)}**\n")
        print(f"Mean of {len(lenses)} lens score{'s' if len(lenses) != 1 else ''} {mean:.1f}{capped}.{partial}\n")
        print("| Lens | Score | Gauge | Weakest aspect | Findings behind it | How it was computed |")
        print("|---|---|---|---|---|---|")
        for name, score, note, (aspect, grade, ids) in lenses:
            print(f"| {name} | {score:.1f} | {gauge(score)} | {aspect} ({grade:g}) | {', '.join(ids) or '—'} | {note} |")
        print("\n### Every aspect, lowest grade first\n")
        print("| Lens | Aspect | Grade | Gauge |")
        print("|---|---|---|---|")
        graded = sorted((a for a in all_aspects if a[2] is not None), key=lambda a: (a[2], a[0], a[1]))
        for name, aspect, grade, _ in graded:
            shown = int(grade) if float(grade).is_integer() else grade
            print(f"| {name} | {aspect} | {grade:g} | {gauge(shown)} |")
        for name, aspect, _, state in (a for a in all_aspects if a[2] is None):
            print(f"| {name} | {aspect} | {state} | — |")
    if problems:
        print("\n### Scorecard problems to fix before publishing\n")
        for p in problems:
            print(f"- {p}")
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
