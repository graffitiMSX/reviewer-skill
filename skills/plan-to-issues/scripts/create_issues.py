#!/usr/bin/env python3
"""Create GitHub issues from docs/remediation/tickets.md in dependency order.

Usage:
  create_issues.py tickets.md                 # dry run: validate and print order
  create_issues.py tickets.md --create        # create issues with gh
      [--repo owner/name] [--milestone NAME] [--create-missing-labels]
  create_issues.py tickets.md --fix-refs      # finish issues left with T-nn text or {number}

Format expected (written by the ticket-writer agent):

  ## Labels to create
  - `tech-debt` — #d93f0b — declared by technical_debt_template.md

  ## T-01 — [BUG-{number}] Title
  - template: bug_template.md
  - labels: `bug`, `priority:p1`
  - milestone: none
  - depends: `T-03`, `#289`, or none
  - assignee: none

  ~~~markdown
  # Bug: [BUG-{number}] Title
  <issue body>
  ~~~

`{number}` in a title or body becomes the zero-padded issue number (#17 -> 017)
right after the issue is created, following repos whose templates use
`[BUG-000]`-style work-item IDs. `T-nn` references become `#numbers`; references
to tickets created later are patched in a final pass. `#123` in `depends:` names
an existing issue and is ignored for ordering. Colors listed under
"## Labels to create" are used when --create-missing-labels creates a label.

After each creation the mapping `- T-01 → #123` is appended under
`## Created issues`, so a rerun skips tickets that already exist.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HEADER = re.compile(r"^## (T-\d+)\s*[—–:-]\s*(.+?)\s*$")
CREATED_HEADER = re.compile(r"^## Created issues\s*$")
LABELS_HEADER = re.compile(r"^## Labels to create\s*$")
MAPPING = re.compile(r"(T-\d+)\D+#(\d+)")
LABEL_SPEC = re.compile(r"^-\s*`([^`]+)`(.*)$")
COLOR = re.compile(r"#([0-9a-fA-F]{6})\b")
NUMBER = "{number}"
NUMBER_WIDTH = 3
FENCE = "~~~"


def split_list(value):
    value = value.strip()
    if not value or value.lower() in {"none", "-", "n/a"}:
        return []
    items = [v.strip().strip("`").strip() for v in value.split(",")]
    return [v for v in items if v and v.lower() != "none"]


def parse(path):
    tickets, created, label_specs = [], {}, {}
    current, in_fence, section = None, False, None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if in_fence:
            if line.strip() == FENCE:
                in_fence = False
            else:
                current["body"].append(line)
            continue
        if CREATED_HEADER.match(line):
            section, current = "created", None
            continue
        if LABELS_HEADER.match(line):
            section, current = "labels", None
            continue
        m = HEADER.match(line)
        if m:
            section = None
            current = {"id": m.group(1), "title": m.group(2), "labels": [],
                       "milestone": "", "depends": [], "assignee": "", "body": []}
            tickets.append(current)
            continue
        if line.startswith("## "):
            section, current = None, None
            continue
        if section == "created":
            m = MAPPING.search(line)
            if m:
                created[m.group(1)] = int(m.group(2))
            continue
        if section == "labels":
            m = LABEL_SPEC.match(line)
            if m:
                rest = m.group(2)
                color = COLOR.search(rest)
                desc = COLOR.sub("", rest).strip(" —–-:")
                label_specs[m.group(1)] = {"color": color.group(1) if color else None,
                                           "description": desc[:100]}
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
    return tickets, created, label_specs


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
            if d.startswith("#"):
                continue  # existing GitHub issue; nothing to create or order
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


def ensure_labels(tickets, repo_args, create_missing, specs):
    existing = {l["name"] for l in json.loads(gh("label", "list", "--limit", "500", "--json", "name", *repo_args))}
    wanted = {l for t in tickets for l in t["labels"]}
    missing = sorted(wanted - existing)
    if not missing:
        return
    if not create_missing:
        sys.exit("error: labels missing in repo: " + ", ".join(missing)
                 + "\n       create them or rerun with --create-missing-labels")
    for name in missing:
        spec = specs.get(name, {})
        cmd = ["label", "create", name, "--description", spec.get("description") or "remediation pipeline"]
        if spec.get("color"):
            cmd += ["--color", spec["color"]]
        gh(*cmd, *repo_args)
        print(f"created label {name}" + (f" (#{spec['color']})" if spec.get("color") else ""))


def append_mapping(path, tid, number):
    text = path.read_text(encoding="utf-8")
    if not re.search(r"^## Created issues\s*$", text, re.M):
        text = text.rstrip("\n") + "\n\n## Created issues\n"
    text = text.rstrip("\n") + f"\n- {tid} → #{number}\n"
    path.write_text(text, encoding="utf-8")


def write_temp(text):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        return fh.name


def render(body, mapping):
    """Replace T-nn references with #numbers for every ticket in mapping."""
    for tid, num in mapping.items():
        body = re.sub(rf"`?\b{tid}\b`?", f"#{num}", body)
    return body


def fill_number(text, number):
    """Fill the work-item number placeholder; zeros before the issue exists, as templates do."""
    return text.replace(NUMBER, str(number).zfill(NUMBER_WIDTH) if number else "0" * NUMBER_WIDTH)


def normalize(text):
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()


def has_placeholder(t):
    return NUMBER in t["title"] or NUMBER in t["body"]


def posted(t, created):
    """Title and body as this script last wrote them for an already-created ticket."""
    num = created[t["id"]]
    if has_placeholder(t):  # finished right after creation, with everything created up to then
        known = {tid: n for tid, n in created.items() if n <= num}
        return fill_number(t["title"], num), fill_number(render(t["body"], known), num)
    known = {tid: n for tid, n in created.items() if n < num}
    return t["title"], render(t["body"], known)


def wanted(t, created):
    num = created[t["id"]]
    return fill_number(t["title"], num), fill_number(render(t["body"], created), num)


def needs_sync(t, created):
    return normalize(posted(t, created)[1]) != normalize(wanted(t, created)[1])


def sync_issues(tickets, created, repo_args):
    """Finish created issues: resolve late T-nn references and fill {number} placeholders.

    A title or body is only overwritten when it still matches what this script
    posted, so edits made on GitHub since creation are never lost.
    """
    todo = [t for t in tickets if t["id"] in created and (needs_sync(t, created) or has_placeholder(t))]
    updated, current_ok, skipped = 0, 0, []
    for t in todo:
        num = created[t["id"]]
        want_title, want_body = wanted(t, created)
        post_title, post_body = posted(t, created)
        before_title = {post_title, fill_number(t["title"], None)}  # also the pre-fill title
        before_body = {normalize(post_body), normalize(fill_number(render(
            t["body"], {tid: n for tid, n in created.items() if n < num}), None))}
        issue = json.loads(gh("issue", "view", str(num), "--json", "title,body", *repo_args))
        cmd, conflicts = [], []
        if issue["title"] != want_title:
            if issue["title"] in before_title:
                cmd += ["--title", want_title]
            else:
                conflicts.append("title")
        if normalize(issue["body"]) != normalize(want_body):
            if normalize(issue["body"]) in before_body:
                cmd += ["--body-file", write_temp(want_body)]
            else:
                conflicts.append("body")
        if conflicts:
            skipped.append(f"{t['id']} (#{num}: {', '.join(conflicts)})")
        if not cmd:
            current_ok += 0 if conflicts else 1
            continue
        gh("issue", "edit", str(num), *cmd, *repo_args)
        updated += 1
        print(f"updated {t['id']} (#{num})")
        time.sleep(1)
    print(f"sync: {updated} issues updated, {current_ok} already current")
    if skipped:
        print("skipped, edited on GitHub since creation (fix by hand): " + ", ".join(skipped), file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickets", type=Path)
    ap.add_argument("--create", action="store_true", help="actually create issues (default: dry run)")
    ap.add_argument("--repo", help="owner/name; default is the current repo")
    ap.add_argument("--milestone", help="override milestone for every ticket")
    ap.add_argument("--create-missing-labels", action="store_true")
    ap.add_argument("--fix-refs", action="store_true",
                    help="finish created issues that still hold T-nn text or {number} placeholders")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    tickets, created, label_specs = parse(args.tickets)
    if not tickets:
        sys.exit("error: no tickets found (expected headings like '## T-01 — Title')")
    problems = [t["id"] for t in tickets if not t["body"].strip()]
    if problems:
        sys.exit("error: empty body (missing ~~~markdown fence?) in " + ", ".join(problems))
    ordered = order(tickets)

    print(f"{'order':<6}{'ticket':<8}{'status':<10}{'depends':<16}{'labels':<30}title")
    for i, t in enumerate(ordered, 1):
        status = f"#{created[t['id']]}" if t["id"] in created else "pending"
        print(f"{i:<6}{t['id']:<8}{status:<10}{','.join(t['depends']) or '-':<16}"
              f"{','.join(t['labels'])[:28]:<30}{fill_number(t['title'], created.get(t['id']))}")

    repo_args = ["--repo", args.repo] if args.repo else []
    if args.fix_refs:
        sync_issues(ordered, created, repo_args)
        return
    if not args.create:
        print(f"\ndry run: {len(ordered)} tickets, {len(created)} already created. Add --create to proceed.")
        stale = [t for t in ordered if t["id"] in created and needs_sync(t, created)]
        if stale:
            print(f"{len(stale)} created issues may still hold T-nn text for later tickets; "
                  "run with --fix-refs to update them.")
        return

    ensure_labels([t for t in ordered if t["id"] not in created], repo_args,
                  args.create_missing_labels, label_specs)

    for t in ordered:
        if t["id"] in created:
            continue
        cmd = ["issue", "create", "--title", fill_number(t["title"], None),
               "--body-file", write_temp(fill_number(render(t["body"], created), None)), *repo_args]
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
        time.sleep(1)  # GitHub asks for >=1s between content-creating requests
        if has_placeholder(t):
            title, body = wanted(t, created)
            gh("issue", "edit", str(number), "--title", title, "--body-file", write_temp(body), *repo_args)
            time.sleep(1)

    # Tickets that cite tickets created later in the run still hold T-nn text; patch them now.
    sync_issues(ordered, created, repo_args)
    print(f"\ndone: {len(created)} issues mapped in {args.tickets}")


if __name__ == "__main__":
    main()
