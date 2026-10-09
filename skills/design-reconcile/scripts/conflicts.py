#!/usr/bin/env python3
"""Support the cross-lens conflict check of a design review.

Usage:
  conflicts.py candidates docs/remediation
  conflicts.py check docs/remediation/design-review-conflicts.md docs/remediation

The reports argument is a folder holding design-review-<lens>.md files (or the
merged design-review.md when the lens files are gone), or explicit report files.

Deciding whether two remediations contradict each other is judgement, and the
conflict-reviewer agent does it. This script does the parts that are not:

  candidates   lists every path cited by two or more findings, most lenses
               first, so the reviewer knows where fixes land on the same code.
               It is a starting point; conflicts of policy share no file.
  check        validates the conflict report: every X-nnn names at least two
               findings that exist in the reports, has a resolution of a known
               kind, and the Order lines of all conflicts together contain no
               cycle, so the plan never has to fix A before B and B before A.
               An Order line is a chain of steps, each one or more findings:
               `F-ARC-001, F-BE-008 → F-BE-010 → F-ARC-007`.

`check` exits 1 when it finds a problem, so the skill's quality gate can rely
on it.
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve()
SCORECARD_DIR = HERE.parents[2] / "design-review" / "scripts"
sys.path.insert(0, str(SCORECARD_DIR))
try:
    import scorecard as sc
except ImportError:
    sys.exit(f"error: cannot import scorecard.py from {SCORECARD_DIR}; the design-review skill must sit next to this one")

CONFLICTS_FILE = "design-review-conflicts.md"
TYPES = ["opposing", "undoes", "divergent", "same-code", "ordering", "trade-off"]
RESOLUTIONS = ["combined", "prefer", "sequence", "decision"]
CONFLICT = re.compile(r"^#{2,4}\s*(X-\d+)\s*\[([^\]]+)\]", re.M)
FIELD = r"\*\*{name}\*\*\s*:?\s*([^\n]*)"
CODE_SPAN = re.compile(r"`([^`\n]+)`")
PATH = re.compile(r"^[\w.@\-\[\]()]+(?:/[\w.@\-\[\]()]+)*\.[A-Za-z][A-Za-z0-9]{0,5}$")
ARROW = re.compile(r"\s*(?:→|->|=>)\s*")


def report_paths(args):
    paths = []
    for arg in args:
        p = Path(arg)
        if p.is_dir():
            lens_files = [p / f"design-review-{l}.md" for l in sc.LENSES if (p / f"design-review-{l}.md").exists()]
            paths += lens_files or ([p / "design-review.md"] if (p / "design-review.md").exists() else [])
        elif p.name != CONFLICTS_FILE:
            paths.append(p)
    if not paths:
        sys.exit("error: no design-review reports found")
    return paths


def finding_blocks(text):
    """finding id -> (severity, title, block text)."""
    blocks = {}
    marks = list(sc.FINDING.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        # a finding ends at the next heading of its own level or above, so the
        # last one does not swallow the tables and test plan that follow it
        depth = len(m.group(0)) - len(m.group(0).lstrip("#"))
        closing = re.compile(r"^#{1,%d}\s" % depth, re.M).search(text, m.end(), end)
        end = closing.start() if closing else end
        title = text[m.end(): text.find("\n", m.end())].strip(" ]")
        blocks.setdefault(m.group(1).upper(), (m.group(2).capitalize(), title, text[m.end(): end]))
    return blocks


def all_findings(paths):
    found = {}
    for path in paths:
        for fid, block in finding_blocks(path.read_text(encoding="utf-8")).items():
            found.setdefault(fid, block)
    return found


def cited_paths(block):
    paths = set()
    for span in CODE_SPAN.findall(block):
        for token in span.split():
            token = re.sub(r"[:#]L?\d+(?:[-–,]L?\d+)*$", "", token.strip("(),;"))
            if "/" in token and PATH.match(token):
                paths.add(token.lstrip("./"))
    return paths


def candidates(args):
    findings = all_findings(report_paths(args))
    # reviewers cite the same file with and without its leading folders, so
    # group by the last two components and show the longest spelling seen
    by_key, spelling = defaultdict(set), {}
    for fid, (_, _, block) in findings.items():
        for path in cited_paths(block):
            key = "/".join(path.split("/")[-2:])
            by_key[key].add(fid)
            spelling[key] = max(spelling.get(key, ""), path, key=len)
    shared = {spelling[k]: ids for k, ids in by_key.items() if len(ids) > 1}
    lenses = lambda ids: {i.split("-")[1] for i in ids}
    print(f"## Shared ground: {len(shared)} paths cited by two or more of {len(findings)} findings\n")
    print("| Path | Lenses | Findings |")
    print("|---|---|---|")
    for path, ids in sorted(shared.items(), key=lambda kv: (-len(lenses(kv[1])), -len(kv[1]), kv[0])):
        print(f"| `{path}` | {len(lenses(ids))} | {', '.join(sorted(ids))} |")
    if not shared:
        print("| — | — | no path is cited by more than one finding |")


def field(block, name):
    m = re.search(FIELD.format(name=name), block, re.I)
    return m.group(1).strip() if m else None


def find_cycle(edges):
    graph = defaultdict(set)
    for a, b in edges:
        graph[a].add(b)
    state, stack = {}, []

    def visit(node):
        state[node] = 1
        stack.append(node)
        for nxt in sorted(graph[node]):
            if state.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if nxt not in state:
                cycle = visit(nxt)
                if cycle:
                    return cycle
        stack.pop()
        state[node] = 2
        return None

    for node in sorted(graph):
        if node not in state:
            cycle = visit(node)
            if cycle:
                return cycle
    return None


def check(args):
    if len(args) < 2:
        sys.exit(__doc__)
    report = Path(args[0])
    if not report.exists():
        sys.exit(f"error: {report} does not exist")
    findings = all_findings(report_paths(args[1:]))
    text = report.read_text(encoding="utf-8")
    problems, edges, counts = [], {}, defaultdict(int)
    marks = list(CONFLICT.finditer(text))
    seen = set()
    for i, m in enumerate(marks):
        xid, kind = m.group(1).upper(), m.group(2).strip().lower()
        block = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        if xid in seen:
            problems.append(f"{xid}: appears more than once")
        seen.add(xid)
        if kind not in TYPES:
            problems.append(f"{xid}: type `{kind}` is not one of {', '.join(TYPES)}")
        ids = sorted(set(f.upper() for f in sc.FINDING_ID.findall(field(block, "Findings") or "")))
        if len(ids) < 2:
            problems.append(f"{xid}: the Findings line must name at least two findings")
        for fid in ids:
            if fid not in findings:
                problems.append(f"{xid}: cites {fid}, which is not in the review reports")
        resolution = (field(block, "Resolution") or "").lower().lstrip("`* ")
        chosen = next((r for r in RESOLUTIONS if resolution.startswith(r)), None)
        if not chosen:
            problems.append(f"{xid}: Resolution must start with one of {', '.join(RESOLUTIONS)}")
        counts[chosen or "unresolved"] += 1
        if chosen == "prefer":
            winner = sc.FINDING_ID.findall(resolution.upper())
            if not winner or winner[0] not in ids:
                problems.append(f"{xid}: `prefer` must name the finding of this conflict whose remediation stands")
        order = field(block, "Order") or ""
        steps = [s for s in (sc.FINDING_ID.findall(part.upper()) for part in ARROW.split(order)) if s]
        if chosen == "sequence" and len(steps) < 2:
            problems.append(f"{xid}: a `sequence` resolution needs an Order line such as `F-BE-003 → F-SEC-007`")
        for fid in sorted({f for step in steps for f in step} - set(findings)):
            problems.append(f"{xid}: the Order line names {fid}, which is not in the review reports")
        for before, after in zip(steps, steps[1:]):
            for a in before:
                for b in after:
                    edges.setdefault((a, b), xid)
        for name in ("What each asks for", "If both are applied as written", "Resolved remediation", "Verification"):
            if not re.search(FIELD.format(name=name), block, re.I):
                problems.append(f"{xid}: missing **{name}**")
    cycle = find_cycle(edges)
    if cycle:
        hops = [f"{a} → {b} ({edges[(a, b)]})" for a, b in zip(cycle, cycle[1:])]
        problems.append("the Order lines form a cycle, so no fix order satisfies them: " + "; ".join(hops))

    summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "none"
    print(f"{len(marks)} conflicts across {len(findings)} findings ({summary}); {len(edges)} ordering constraints, {'cycle found' if cycle else 'no cycle'}.")
    if problems:
        print("\n### Conflict report problems to fix before publishing\n")
        for p in problems:
            print(f"- {p}")
        sys.exit(1)


def main(argv):
    if len(argv) < 2 or argv[0] not in ("candidates", "check"):
        sys.exit(__doc__)
    (candidates if argv[0] == "candidates" else check)(argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
