#!/usr/bin/env python3
"""Collect the decisions a review must respect, from the repo and the pipeline.

Usage:
  decisions.py collect <repo> [<remediation dir>] [-o <file>]

Writes one markdown digest (default: stdout) that every lens reads before it
grades anything:

  1. Decision records in the repo: ADR-style files under the usual folders,
     with title and status (accepted, superseded, ...).
  2. Repo instructions that carry decisions: AGENTS.md, CLAUDE.md,
     ARCHITECTURE.md and the like, by path.
  3. The pipeline's decision register, <remediation dir>/decisions.md: one
     `## D-nnn Title` entry per decision the team settled during a review.
  4. Decisions still open: `decision` conflicts in design-review-conflicts.md
     that no D-nnn cites yet.

The default remediation dir is <repo>/docs/remediation. Memory search is not
done here; the skill appends what /design-memory finds.

Exit status is 1 when the register has an entry without a Status, Decision or
Why line, or a Status other than accepted or superseded, so the gate catches a
malformed register before reviewers rely on it.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

RECORD_DIRS = ["docs/adr", "docs/adrs", "docs/decisions", "docs/architecture/decisions", "doc/adr", "doc/decisions",
               "adr", "adrs", "decisions", "architecture/decisions", ".adr"]
RECORD_NAME = re.compile(r"(^|[-_/])(adr|decision)s?[-_ ]?\d+", re.I)
INSTRUCTION_FILES = ["AGENTS.md", "CLAUDE.md", "ARCHITECTURE.md", "DESIGN.md", "docs/architecture.md", "docs/ARCHITECTURE.md",
                     "CONTRIBUTING.md", ".github/copilot-instructions.md"]
SKIP = {"node_modules", ".git", "dist", "build", "vendor", ".venv", "venv", "remediation", ".claude", "worktrees"}
ENTRY = re.compile(r"^## (D-\d{3,})\s+(.+)$", re.M)
CONFLICT = re.compile(r"^#{2,4} (X-\d{3,})\b[^\n]*$", re.M)


def markdown_files(repo):
    """Tracked and untracked-but-not-ignored .md files; os walk when not a git repo."""
    try:
        listed = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "*.md"], cwd=repo,
                                capture_output=True, text=True, timeout=60)
        names = listed.stdout.splitlines() if listed.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        names = None
    paths = [repo / n for n in names] if names is not None else list(repo.rglob("*.md"))
    return [p for p in paths if p.is_file() and not SKIP.intersection(p.relative_to(repo).parts)]


def first_heading(text):
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def record_status(text):
    # MADR frontmatter `status: accepted`, `Status: Accepted` lines, or a `## Status` section
    m = re.search(r"^\s*[-*]?\s*\**status\**\s*:\s*\**([^\n*]+)", text, re.I | re.M)
    if not m:
        m = re.search(r"^#+\s*status\s*\n+\s*([^\n]+)", text, re.I | re.M)
    return m.group(1).strip().rstrip(".") if m else "not stated"


def decision_records(repo, md):
    found = set()
    for p in md:
        rel = p.relative_to(repo).as_posix()
        in_dir = any(rel.startswith(d + "/") for d in RECORD_DIRS)
        if (in_dir and p.name.lower() not in ("readme.md", "template.md", "index.md")) or RECORD_NAME.search(rel):
            found.add(p)
    rows = []
    for p in sorted(found):
        text = p.read_text(encoding="utf-8", errors="replace")
        rows.append((p.relative_to(repo).as_posix(), first_heading(text) or p.stem, record_status(text)))
    return rows


def instruction_files(repo, md):
    out = [f for f in INSTRUCTION_FILES if (repo / f).is_file()]
    # nested AGENTS.md / CLAUDE.md scope rules to a folder
    out += sorted(p.relative_to(repo).as_posix() for p in md
                  if p.name in ("AGENTS.md", "CLAUDE.md") and len(p.relative_to(repo).parts) > 1)
    return out


def field(block, label):
    m = re.search(rf"^- \*\*{label}\*\*:\s*(.*)$", block, re.M)
    return m.group(1).strip() if m else None


def register(path):
    if not path.is_file():
        return [], []
    text = path.read_text(encoding="utf-8")
    heads = list(ENTRY.finditer(text))
    entries, problems = [], []
    for i, h in enumerate(heads):
        block = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        did, title = h.group(1), h.group(2).strip()
        status = field(block, "Status")
        for label in ("Status", "Decision", "Why"):
            if not field(block, label):
                problems.append(f"{did}: no **{label}** line")
        if status and not re.match(r"(accepted|superseded)\b", status, re.I):
            problems.append(f"{did}: status '{status}' is neither accepted nor superseded")
        entries.append({"id": did, "title": title, "status": status or "?", "applies": field(block, "Applies to") or "",
                        "accepts": field(block, "Accepts") or "", "source": field(block, "Source") or "", "block": block})
    ids = [e["id"] for e in entries]
    problems += [f"{d}: used twice" for d in sorted({d for d in ids if ids.count(d) > 1})]
    return entries, problems


def open_conflicts(rem, entries):
    path = rem / "design-review-conflicts.md"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    heads = list(CONFLICT.finditer(text))
    cited = " ".join(e["source"] + " " + e["block"] for e in entries)
    out = []
    for i, h in enumerate(heads):
        block = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        res = field(block, "Resolution") or ""
        if res.lower().startswith("decision") and not re.search(rf"\b{h.group(1)}\b", cited):
            out.append(h.group(0).lstrip("# ").strip())
    return out


def table(head, rows, empty):
    if not rows:
        return empty + "\n"
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("repo")
    c.add_argument("remediation", nargs="?")
    c.add_argument("-o", "--out")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    rem = Path(args.remediation).resolve() if args.remediation else repo / "docs" / "remediation"
    md = markdown_files(repo)
    records = decision_records(repo, md)
    instructions = instruction_files(repo, md)
    entries, problems = register(rem / "decisions.md")
    pending = open_conflicts(rem, entries)

    out = ["# Recorded decisions\n",
           "Read these before grading. A finding that touches one cites it with a **Decision** line, as the conventions file describes.\n",
           f"## Decision records in the repo: {len(records)}\n",
           table(["File", "Title", "Status"], [(f"`{p}`", t, s) for p, t, s in records], "None found in the usual places."),
           f"\n## Repo instructions that may carry decisions: {len(instructions)}\n",
           ("\n".join(f"- `{p}`" for p in instructions) + "\n") if instructions else "None.\n",
           f"\n## Decision register (`{(rem / 'decisions.md').relative_to(repo) if rem.is_relative_to(repo) else rem / 'decisions.md'}`): {len(entries)}\n",
           table(["Decision", "Title", "Status", "Applies to", "Accepts"],
                 [(e["id"], e["title"], e["status"], e["applies"], e["accepts"]) for e in entries], "No register yet."),
           f"\n## Still open, not to be treated as decided: {len(pending)}\n",
           ("\n".join(f"- {p}" for p in pending) + "\n") if pending else "None.\n"]
    if problems:
        out += ["\n## Register problems\n", "\n".join(f"- {p}" for p in problems) + "\n"]
    text = "\n".join(out)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"decisions digest written to {args.out}: {len(records)} records, {len(entries)} register entries, {len(pending)} open")
    else:
        print(text)
    for p in problems:
        print("register problem: " + p, file=sys.stderr)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
