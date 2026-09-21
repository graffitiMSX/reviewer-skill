#!/usr/bin/env python3
"""Create GitHub issues from docs/remediation/tickets.md in dependency order.

Usage:
  create_issues.py tickets.md                 # dry run: validate and print order
  create_issues.py tickets.md --create        # create issues with gh
      [--repo owner/name] [--milestone NAME] [--create-missing-labels]

Format expected (written by the ticket-writer agent):

  ## T-01 — Title
  - labels: `reliability`, `P1`
  - milestone: none
  - depends: `T-03`, or none
  - assignee: none

  ~~~markdown
  <issue body>
  ~~~

After each successful creation the mapping `- T-01 → #123` is appended under
`## Created issues`, so a rerun skips tickets that already exist and rewrites
`T-nn` references in later bodies to the real `#numbers`.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HEADER = re.compile(r"^## (T-\d+)\s*[—–:-]\s*(.+?)\s*$")
CREATED_HEADER = re.compile(r"^## Created issues\s*$")
MAPPING = re.compile(r"(T-\d+)\D+#(\d+)")
FENCE = "~~~"


def split_list(value):
    value = value.strip()
    if not value or value.lower() in {"none", "-", "n/a"}:
        return []
    items = [v.strip().strip("`").strip() for v in value.split(",")]
    return [v for v in items if v and v.lower() != "none"]


def parse(path):
    tickets, created = [], {}
    current, in_fence, in_created = None, False, False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if in_fence:
            if line.strip() == FENCE:
                in_fence = False
            else:
                current["body"].append(line)
            continue
        if CREATED_HEADER.match(line):
            in_created, current = True, None
            continue
        if in_created:
            m = MAPPING.search(line)
            if m:
                created[m.group(1)] = int(m.group(2))
            if line.startswith("## "):
                in_created = False
            continue
        m = HEADER.match(line)
        if m:
            current = {"id": m.group(1), "title": m.group(2), "labels": [],
                       "milestone": "", "depends": [], "assignee": "", "body": []}
            tickets.append(current)
            continue
        if current is None:
            continue
        if line.startswith(FENCE):
            in_fence = True
            continue
        lm = re.match(r"^-\s*(labels|milestone|depends|assignee)\s*:\s*(.*)$", line, re.I)
        if lm:
            key, val = lm.group(1).lower(), lm.group(2)
            if key in ("labels", "depends"):
                current[key] = split_list(val)
            else:
                v = val.strip().strip("`").strip()
                current[key] = "" if v.lower() in {"none", ""} else v
    for t in tickets:
        t["body"] = "\n".join(t["body"]).strip() + "\n"
    return tickets, created


def order(tickets):
    by_id = {t["id"]: t for t in tickets}
    done, out, visiting = set(), [], set()

    def visit(t):
        if t["id"] in done:
            return
        if t["id"] in visiting:
            sys.exit(f"error: dependency cycle involving {t['id']}")
        visiting.add(t["id"])
        for d in t["depends"]:
            if d not in by_id:
                print(f"warning: {t['id']} depends on unknown {d}", file=sys.stderr)
                continue
            visit(by_id[d])
        visiting.discard(t["id"])
        done.add(t["id"])
        out.append(t)

    for t in tickets:
        visit(t)
    return out


def gh(*args, capture=True):
    res = subprocess.run(["gh", *args], text=True, capture_output=capture)
    if res.returncode != 0:
        sys.exit(f"error: gh {' '.join(args)}\n{res.stderr if capture else ''}")
    return res.stdout.strip() if capture else ""


def ensure_labels(tickets, repo_args, create_missing):
    existing = {l["name"] for l in json.loads(gh("label", "list", "--limit", "500", "--json", "name", *repo_args))}
    wanted = {l for t in tickets for l in t["labels"]}
    missing = sorted(wanted - existing)
    if not missing:
        return
    if not create_missing:
        sys.exit("error: labels missing in repo: " + ", ".join(missing)
                 + "\n       create them or rerun with --create-missing-labels")
    for name in missing:
        gh("label", "create", name, "--description", "remediation pipeline", *repo_args)
        print(f"created label {name}")


def append_mapping(path, tid, number):
    text = path.read_text(encoding="utf-8")
    if not re.search(r"^## Created issues\s*$", text, re.M):
        text = text.rstrip("\n") + "\n\n## Created issues\n"
    text = text.rstrip("\n") + f"\n- {tid} → #{number}\n"
    path.write_text(text, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickets", type=Path)
    ap.add_argument("--create", action="store_true", help="actually create issues (default: dry run)")
    ap.add_argument("--repo", help="owner/name; default is the current repo")
    ap.add_argument("--milestone", help="override milestone for every ticket")
    ap.add_argument("--create-missing-labels", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    tickets, created = parse(args.tickets)
    if not tickets:
        sys.exit("error: no tickets found (expected headings like '## T-01 — Title')")
    problems = [t["id"] for t in tickets if not t["body"].strip()]
    if problems:
        sys.exit("error: empty body (missing ~~~markdown fence?) in " + ", ".join(problems))
    ordered = order(tickets)

    print(f"{'order':<6}{'ticket':<8}{'status':<10}{'depends':<16}{'labels':<30}title")
    for i, t in enumerate(ordered, 1):
        status = f"#{created[t['id']]}" if t["id"] in created else "pending"
        print(f"{i:<6}{t['id']:<8}{status:<10}{','.join(t['depends']) or '-':<16}{','.join(t['labels'])[:28]:<30}{t['title']}")
    if not args.create:
        print(f"\ndry run: {len(ordered)} tickets, {len(created)} already created. Add --create to proceed.")
        return

    repo_args = ["--repo", args.repo] if args.repo else []
    ensure_labels([t for t in ordered if t["id"] not in created], repo_args, args.create_missing_labels)

    for t in ordered:
        if t["id"] in created:
            continue
        body = t["body"]
        for tid, num in created.items():
            body = re.sub(rf"`?\b{tid}\b`?", f"#{num}", body)
        unresolved = sorted(set(re.findall(r"\bT-\d+\b", body)) - {t["id"]})
        if unresolved:
            print(f"warning: {t['id']} still references {', '.join(unresolved)} (not created yet)", file=sys.stderr)
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(body)
            body_file = fh.name
        cmd = ["issue", "create", "--title", t["title"], "--body-file", body_file, *repo_args]
        for label in t["labels"]:
            cmd += ["--label", label]
        milestone = args.milestone or t["milestone"]
        if milestone:
            cmd += ["--milestone", milestone]
        if t["assignee"]:
            cmd += ["--assignee", t["assignee"]]
        url = gh(*cmd)
        m = re.search(r"/issues/(\d+)", url)
        if not m:
            sys.exit(f"error: could not parse issue number from gh output: {url}")
        number = int(m.group(1))
        created[t["id"]] = number
        append_mapping(args.tickets, t["id"], number)
        print(f"created {t['id']} → #{number}  {url}")

    print(f"\ndone: {len(created)} issues mapped in {args.tickets}")


if __name__ == "__main__":
    main()
