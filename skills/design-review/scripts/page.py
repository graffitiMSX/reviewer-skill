#!/usr/bin/env python3
"""Render a pipeline artifact as one HTML page a person can read and explore.

Usage:
  page.py <stage> <remediation dir> [--source FILE] [--out DIR] [--name REPO]

  stage     code-map | review | conflicts | plan | tickets | dispatch | rereview
  default source, relative to the remediation dir:
    code-map   code-map/graph.json and its markdown views
    review     design-review.md, or the design-review-<lens>.md files
    conflicts  design-review-conflicts.md
    plan       action-plan.md          tickets   tickets.md
    dispatch   dispatch.md             rereview  the newest design-rereview-<date>.md

It writes two files under <remediation dir>/pages/:
  <stage>.html            a complete document, to open in a browser
  artifact/<stage>.html   the same page without the document wrapper, which is
                          the form a claude.ai Artifact is published from

The page is the source document rendered whole, so nothing is summarised away,
with a dashboard on top computed from the same text: scores and grades, counts
by severity, a graph of folders or of colliding fixes, before and after. Every
F-, X-, A-, T- and G- identifier links to its entry, long tables can be
filtered and sorted, and sections fold. No model writes any of it.
"""
import argparse
import html
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scorecard as sc  # noqa: E402

ITEM_ID = re.compile(r"\b(F-(?:ARC|BE|FE|UX|SEC|DB)-\d+|[XAGT]-\d+)\b")
ITEM_HEAD = re.compile(r"^(F-(?:ARC|BE|FE|UX|SEC|DB)-\d+|[XAGT]-\d+)\b\s*(?:\[([^\]]+)\])?\s*[—–:-]?\s*(.*)$")
SEVERITY = {"critical": "critical", "high": "serious", "medium": "warning", "p0": "critical", "p1": "serious", "p2": "warning"}
LENS = {"ARC": "architecture", "BE": "backend", "FE": "front end", "UX": "UX", "SEC": "security", "DB": "database"}
TITLES = {"code-map": "Code Map", "review": "Design Review", "conflicts": "Fix Conflicts", "plan": "Action Plan",
          "tickets": "Remediation Tickets", "dispatch": "Fix Dispatch", "rereview": "Design Re-review"}


def esc(text):
    return html.escape(str(text), quote=True)


# ---------- markdown to html ----------

def inline(text, known):
    out, parts = [], re.split(r"(`[^`]*`)", text)
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{esc(part[1:-1])}</code>")
            continue
        part = esc(part)
        part = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', part)
        part = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", part)
        part = re.sub(r"(?<![\w*])\*([^*\s][^*]*)\*(?![\w*])", r"<em>\1</em>", part)
        part = ITEM_ID.sub(lambda m: f'<a class="ref" href="#{m.group(1)}">{m.group(1)}</a>' if m.group(1) in known else m.group(1), part)
        out.append(part.replace("&lt;br&gt;", "<br>").replace("&lt;br/&gt;", "<br>"))
    return "".join(out)


def cells(line):
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def chip(text):
    kind = SEVERITY.get(text.strip().lower().split()[0] if text.strip() else "", "")
    return f'<span class="chip {kind}">{esc(text)}</span>'


def render_table(rows, known):
    head, body = rows[0], rows[2:] if len(rows) > 1 and re.fullmatch(r"[\s:|-]+", rows[1]) else rows[1:]
    header = cells(head)
    lines = ['<div class="table-wrap">' + ('<input class="filter" type="search" placeholder="Filter rows" aria-label="Filter rows">' if len(body) > 8 else ""),
             "<table><thead><tr>" + "".join(f"<th>{inline(c, known)}</th>" for c in header) + "</tr></thead><tbody>"]
    for row in body:
        values = cells(row)
        tds = []
        for name, value in zip(header, values + [""] * (len(header) - len(values))):
            is_level = name.lower() in ("severity", "priority") and value
            tds.append(f"<td>{chip(value) if is_level else inline(value, known)}</td>")
        lines.append("<tr>" + "".join(tds) + "</tr>")
    return "\n".join(lines) + "</tbody></table></div>"


def render_blocks(lines, known):
    """markdown lines without headings -> html."""
    out, i, para, lists = [], 0, [], []

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para), known) + "</p>")
            para.clear()

    def close_lists(depth=0):
        while len(lists) > depth:
            out.append(f"</li></{lists.pop()}>")

    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^\s*(```|~~~)\s*(\w*)", line)
        if fence:
            flush()
            close_lists()
            end = next((j for j in range(i + 1, len(lines)) if lines[j].strip().startswith(fence.group(1))), len(lines))
            body = esc("\n".join(lines[i + 1:end]))
            out.append(f'<pre class="mermaid">{body}</pre>' if fence.group(2) == "mermaid" else f"<pre><code>{body}</code></pre>")
            i = end + 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", lines[i + 1]) and "-" in lines[i + 1]:
            flush()
            close_lists()
            end = next((j for j in range(i, len(lines)) if not lines[j].strip().startswith("|")), len(lines))
            out.append(render_table(lines[i:end], known))
            i = end
            continue
        item = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if item:
            flush()
            depth, tag = len(item.group(1)) // 2 + 1, "ol" if item.group(2)[0].isdigit() else "ul"
            if depth > len(lists):
                while depth > len(lists):
                    out.append(f"<{tag}><li>")
                    lists.append(tag)
            else:
                close_lists(depth)
                out.append("</li><li>")
            out.append(inline(item.group(3), known))
        elif not line.strip():
            flush()
            if lists and not (i + 1 < len(lines) and re.match(r"^\s*([-*+]|\d+[.)])\s", lines[i + 1])):
                close_lists()
        elif lists and line.startswith("  "):
            out.append(" " + inline(line.strip(), known))
        elif re.fullmatch(r"\s*([-*_])\1{2,}\s*", line):
            flush()
            close_lists()
        else:
            close_lists()
            para.append(line.strip())
        i += 1
    flush()
    close_lists()
    return "\n".join(out)


def split_sections(text):
    """-> [(level, title, body lines)] in order; level 0 holds anything before the first heading."""
    sections, current, fence = [], (0, "", []), None
    for line in text.splitlines():
        mark = re.match(r"^\s*(```|~~~)", line)
        if mark:
            fence = None if fence == mark.group(1) else (fence or mark.group(1))
        head = None if fence else re.match(r"^(#{1,4})\s+(.*?)\s*#*$", line)
        if head:
            sections.append(current)
            current = (len(head.group(1)), head.group(2), [])
        else:
            current[2].append(line)
    sections.append(current)
    return [s for s in sections if s[1] or any(l.strip() for l in s[2])]


def render_document(text, known):
    """the whole markdown document: ## sections fold, identified ### entries become cards."""
    out, open_section, open_item, first = [], False, False, True

    def close(item_only=False):
        nonlocal open_section, open_item
        if open_item:
            out.append("</div></details>")
            open_item = False
        if open_section and not item_only:
            out.append("</div></details>")
            open_section = False

    for level, title, body in split_sections(text):
        entry = ITEM_HEAD.match(title) if level >= 2 else None
        if entry and entry.group(1) in known:
            close(item_only=True)
            ident, tag, rest = entry.groups()
            lens = LENS.get(ident.split("-")[1], "") if ident.startswith("F-") else ""
            search = esc(" ".join([ident, tag or "", lens, rest]).lower())
            out.append(f'<details class="item" id="{ident}" data-search="{search}"><summary><span class="id">{ident}</span>'
                       + (chip(tag) if tag else "") + f'<span class="item-title">{inline(rest, known)}</span></summary><div class="body">')
            open_item = True
        elif level in (1, 2):
            close()
            if level == 1 and not title.lower().startswith("lens:"):
                out.append(f'<h2 class="part">{inline(title, known)}</h2>')
            else:
                out.append(f'<details class="section"{" open" if first else ""}><summary><h3>{inline(title, known)}</h3></summary><div class="body">')
                open_section, first = True, False
        elif level:
            close(item_only=True)
            out.append(f"<h{min(level + 1, 6)}>{inline(title, known)}</h{min(level + 1, 6)}>")
        out.append(render_blocks(body, known))
    close()
    return "\n".join(out)


def tables_in(text):
    """-> [(header cells, [row cells])] for every pipe table."""
    found, lines, i = [], text.splitlines(), 0
    while i < len(lines) - 1:
        if lines[i].strip().startswith("|") and re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", lines[i + 1]) and "-" in lines[i + 1]:
            end = next((j for j in range(i, len(lines)) if not lines[j].strip().startswith("|")), len(lines))
            found.append((cells(lines[i]), [cells(l) for l in lines[i + 2:end]]))
            i = end
        else:
            i += 1
    return found


def table_with(text, *columns):
    for header, rows in tables_in(text):
        lowered = [h.lower() for h in header]
        if all(c in lowered for c in columns):
            return lowered, rows
    return None, []


def blocks(text, pattern):
    """-> [(id, tag, title, body)] for headings whose text starts with an id matching pattern."""
    out = []
    for level, title, body in split_sections(text):
        entry = ITEM_HEAD.match(title) if level >= 2 else None
        if entry and re.fullmatch(pattern, entry.group(1)):
            out.append((entry.group(1), entry.group(2) or "", entry.group(3), "\n".join(body)))
    return out


def field(body, name):
    m = re.search(r"(?:\*\*)?" + name + r"(?:\*\*)?\s*:\s*([^\n·]*)", body, re.I)
    return m.group(1).strip(" *`") if m else ""


# ---------- dashboard pieces ----------

def tiles(items):
    return '<section class="tiles">' + "".join(
        f'<div class="tile"><div class="tile-value">{esc(value)}</div><div class="tile-label">{esc(label)}</div>'
        + (f'<div class="tile-note">{esc(note)}</div>' if note else "") + "</div>" for label, value, note in items) + "</section>"


def bars(title, rows, top, unit="", note=""):
    """rows of (label, value, link id or None). One measure, one hue; the value is printed beside each bar."""
    if not rows:
        return ""
    out = [f'<figure class="chart"><figcaption>{esc(title)}</figcaption>' + (f'<p class="chart-note">{esc(note)}</p>' if note else "") + '<div class="bars">']
    for label, value, link in rows:
        width = 0 if not top else max(0.0, min(100.0, 100 * value / top))
        name = f'<a href="#{link}">{esc(label)}</a>' if link else esc(label)
        shown = f"{value:g}{unit}"
        out.append(f'<div class="bar-row" title="{esc(label)}: {shown}"><div class="bar-label">{name}</div>'
                   f'<div class="bar-track"><div class="bar-fill" style="width:{width:.1f}%"></div></div><div class="bar-value">{shown}</div></div>')
    return "\n".join(out) + "</div></figure>"


def dumbbells(title, rows, top=10):
    """rows of (label, before or None, after or None)."""
    rows = [r for r in rows if r[1] is not None or r[2] is not None]
    if not rows:
        return ""
    out = [f'<figure class="chart"><figcaption>{esc(title)}</figcaption>'
           '<p class="legend"><span class="dot before"></span>before <span class="dot after"></span>now</p><div class="bars">']
    for label, before, after in rows:
        pos = lambda v: f"{100 * v / top:.1f}%"
        change = "" if before is None or after is None else f"{after - before:+.1f}".replace(".0", "")
        span = ""
        if before is not None and after is not None:
            lo, hi = sorted((before, after))
            span = f'<div class="link" style="left:{pos(lo)};width:{100 * (hi - lo) / top:.1f}%"></div>'
        marks = (f'<div class="dot before" style="left:{pos(before)}"></div>' if before is not None else "") + \
                (f'<div class="dot after" style="left:{pos(after)}"></div>' if after is not None else "")
        shown = f"{'—' if before is None else f'{before:g}'} → {'—' if after is None else f'{after:g}'}" + (f" ({change})" if change else "")
        out.append(f'<div class="bar-row" title="{esc(label)}: {shown}"><div class="bar-label">{esc(label)}</div>'
                   f'<div class="bar-track plain">{span}{marks}</div><div class="bar-value wide">{shown}</div></div>')
    return "\n".join(out) + "</div></figure>"


def count_table(title, counts, order=None):
    keys = [k for k in (order or []) if counts.get(k)] + sorted(k for k in counts if k not in (order or []))
    if not keys:
        return ""
    return (f'<figure class="chart"><figcaption>{esc(title)}</figcaption><div class="counts">'
            + "".join(f'<div class="count">{chip(k)}<span class="count-n">{counts[k]}</span></div>' for k in keys) + "</div></figure>")


def graph_svg(title, nodes, edges, note=""):
    """nodes: [(id, label, link id or None)]; edges: [(a, b, weight, flagged, tooltip)]. Circular layout."""
    if len(nodes) < 2 or not edges:
        return ""
    width, height = 920, 560
    cx, cy, rx, ry = width / 2, height / 2, width / 2 - 250, height / 2 - 36
    place = {}
    for i, (ident, _, _) in enumerate(nodes):
        angle = 2 * math.pi * i / len(nodes) - math.pi / 2
        place[ident] = (cx + rx * math.cos(angle), cy + ry * math.sin(angle), angle)
    heaviest = max(e[2] for e in edges)
    out = [f'<figure class="chart graph"><figcaption>{esc(title)}</figcaption>' + (f'<p class="chart-note">{esc(note)}</p>' if note else ""),
           f'<div class="graph-wrap"><svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}">']
    for a, b, weight, flagged, tip in sorted(edges, key=lambda e: e[3]):
        (x1, y1, _), (x2, y2, _) = place[a], place[b]
        stroke = 1 + 4 * weight / heaviest if heaviest > 1 else 1.5
        out.append(f'<path class="edge{" flagged" if flagged else ""}" d="M{x1:.1f},{y1:.1f} Q{cx:.1f},{cy:.1f} {x2:.1f},{y2:.1f}" '
                   f'stroke-width="{stroke:.1f}" fill="none"><title>{esc(tip)}</title></path>')
    for ident, label, link in nodes:
        x, y, angle = place[ident]
        anchor = "start" if math.cos(angle) > 0.2 else "end" if math.cos(angle) < -0.2 else "middle"
        tx, ty = x + 12 * math.cos(angle), y + 12 * math.sin(angle) + 4
        text = f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}">{esc(label)}</text>'
        out.append(f'<circle class="node" cx="{x:.1f}" cy="{y:.1f}" r="5"><title>{esc(label)}</title></circle>'
                   + (f'<a href="#{link}">{text}</a>' if link else text))
    return "\n".join(out) + "</svg></div></figure>"


# ---------- stages ----------

def lens_parts(text):
    """split a merged review into per-lens texts; a single lens file comes back whole."""
    marks = list(re.finditer(r"^# Lens:\s*(.+?)\s*$", text, re.M))
    if not marks:
        return [text]
    return [text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)] for i, m in enumerate(marks)]


def score_lenses(text):
    """-> [(lens, score, aspects [(aspect, grade)], findings {id: (severity, firm)})]."""
    out = []
    for part in lens_parts(text):
        findings, rows = sc.parse_findings(part), sc.parse_scorecard(part)
        if not findings and not rows:
            continue
        graded = [(a, g) for a, g, state, _, _ in (rows or []) if state == "graded"]
        code = next(iter(findings), "F-?-0").split("-")[1]
        score = None
        if graded:
            score = min(sc.one_decimal(sum(g for _, g in graded) / len(graded)), sc.worst_firm(findings)[0])
        out.append((LENS.get(code, code), score, graded, findings))
    return out


def stage_review(text):
    lenses = score_lenses(text)
    scored = [l for l in lenses if l[1] is not None]
    every = {fid: v for l in lenses for fid, v in l[3].items()}
    severity = Counter(sev for sev, _ in every.values())
    parts, top = [], []
    if scored:
        overall = min(sc.one_decimal(sum(l[1] for l in scored) / len(scored)), sc.worst_firm(every)[0])
        partial = "" if len(scored) == 5 else "partial: " + ", ".join(l[0] for l in scored)
        top.append(("Overall score", f"{overall:.1f} / 10", f"{sc.label(overall)}{' · ' + partial if partial else ''}"))
    top += [("Findings", len(every), f"{severity['Critical']} critical, {severity['High']} high"),
            ("Lenses reviewed", len(lenses), "" if scored else "this review has no scorecard, so there is no score")]
    parts.append(tiles(top))
    if scored:
        parts.append(bars("Score by lens", [(l[0], l[1], None) for l in scored], 10, " / 10",
                          "Mean of the lens's graded aspects, capped while a Critical or High finding is open."))
        aspects = sorted(((f"{l[0]} · {a}", g, None) for l in scored for a, g in l[2]), key=lambda r: r[1])
        parts.append(bars("Every aspect, lowest grade first", aspects, 10))
    parts.append(count_table("Findings by severity", severity, ["Critical", "High", "Medium", "Low", "Informational"]))
    return "".join(parts), {"findings": len(every)}


def stage_conflicts(text):
    found = blocks(text, r"X-\d+")
    kinds = Counter(tag.lower() for _, tag, _, _ in found)
    resolutions = Counter((field(body, "Resolution").lower().split() or ["none"])[0].strip(":") for _, _, _, body in found)
    nodes, edges = {}, []
    for ident, tag, title, body in found:
        ids = sorted(set(sc.FINDING_ID.findall(field(body, "Findings"))))
        for fid in ids:
            nodes[fid] = (fid, fid, fid if fid in text else None)
        edges += [(a, b, 1, resolutions and field(body, "Resolution").lower().startswith("decision"), f"{ident} [{tag}] {title}")
                  for i, a in enumerate(ids) for b in ids[i + 1:]]
    parts = [tiles([("Conflicts", len(found), ""), ("Need a decision", resolutions.get("decision", 0), "the team has to choose"),
                    ("Findings involved", len(nodes), "")]),
             count_table("By type", kinds), count_table("By resolution", resolutions),
             graph_svg("Findings whose fixes collide", sorted(nodes.values()), edges,
                       "A line joins two findings named in the same conflict; a highlighted line is a conflict that needs a decision.")]
    return "".join(parts), {"conflicts": len(found)}


def stage_plan(text):
    found = blocks(text, r"A-\d+")
    priority = Counter(field(body, "Priority").split()[0] if field(body, "Priority") else "unset" for _, _, _, body in found)
    owner = Counter((field(body, "Owner profile") or "unset").split("(")[0].strip()[:40] for _, _, _, body in found)
    kind = Counter((field(body, "Action type") or "unset").split("|")[0].strip()[:30] for _, _, _, body in found)
    covered = {f for _, _, _, body in found for f in sc.FINDING_ID.findall(body.split("**Priority**")[0])}
    parts = [tiles([("Actions", len(found), ""), ("Start first", priority.get("P0", 0), "priority P0"), ("Findings addressed", len(covered), "")]),
             count_table("Actions by priority", priority, ["P0", "P1", "P2", "P3"]),
             bars("Actions by owner profile", [(k, v, None) for k, v in owner.most_common(12)], max(owner.values(), default=0)),
             bars("Actions by type", [(k, v, None) for k, v in kind.most_common(12)], max(kind.values(), default=0))]
    return "".join(parts), {"actions": len(found)}


def stage_tickets(text):
    found = blocks(text, r"T-\d+")
    labels = Counter(l.strip(" `") for _, _, _, body in found for l in field(body, "labels").split(",") if l.strip(" `"))
    priority = Counter({k.split(":")[1].upper(): v for k, v in labels.items() if k.startswith("priority:")})
    areas = [(k.split(":", 1)[1], v, None) for k, v in labels.most_common() if k.startswith("area:")][:12]
    blocked = sum(1 for _, _, _, body in found if field(body, "depends") not in ("", "none"))
    parts = [tiles([("Tickets", len(found), ""), ("Wait on another ticket", blocked, ""), ("Labels in use", len(labels), "")]),
             count_table("Tickets by priority", priority, ["P0", "P1", "P2", "P3"]),
             bars("Tickets by area", areas, max((a[1] for a in areas), default=0))]
    return "".join(parts), {"tickets": len(found)}


def stage_dispatch(text):
    found = blocks(text, r"G-\d+")
    header, rows = table_with(text, "group", "branch")
    merged = sum(1 for r in rows if "merged" in " ".join(r).lower())
    issues = {i for _, _, _, body in found for i in re.findall(r"#(\d+)", field(body, "Included issues"))}
    parts = [tiles([("Groups", len(found), ""), ("Issues in them", len(issues), ""), ("Groups with a merged PR", merged, f"of {len(rows)} in the status table" if rows else "")])]
    return "".join(parts), {"groups": len(found)}


def number(cell):
    m = re.match(r"\s*\**(\d+(?:\.\d+)?)", cell)
    return float(m.group(1)) if m else None


def stage_rereview(text):
    rows, statuses, before_all, after_all = [], Counter(), [], []
    for part in lens_parts(text):
        base_head, base_rows = table_with(part, "aspect", "baseline grade")
        now = {a.lower(): g for a, g, state, _, _ in (sc.parse_scorecard(part) or []) if state == "graded"}
        code = next(iter(sc.FINDING_ID.findall(part)), "F-?-0").split("-")[1]
        for row in base_rows:
            before, after = number(row[base_head.index("baseline grade")]), now.get(row[0].strip("* ").lower())
            rows.append((f"{LENS.get(code, code)} · {row[0].strip('* ')}", before, after))
            before_all += [before] if before is not None else []
            after_all += [after] if after is not None else []
        status_head, status_rows = table_with(part, "finding", "status")
        statuses.update(r[status_head.index("status")].strip("* ") for r in status_rows if len(r) > status_head.index("status"))
    mean = lambda values: f"{sum(values) / len(values):.1f}" if values else "—"
    parts = [tiles([("Mean aspect grade before", mean(before_all), ""), ("Mean aspect grade now", mean(after_all), "the capped scores are in the comparison section below"),
                    ("Earlier findings fixed", statuses.get("Fixed", 0), f"of {sum(statuses.values())} checked")]),
             count_table("Earlier findings by status", statuses, ["Regressed", "Open", "Partially fixed", "Not verifiable", "Accepted", "Fixed"]),
             dumbbells("Every aspect, before and now", sorted(rows, key=lambda r: (r[2] if r[2] is not None else 99)))]
    return "".join(parts), {"aspects": len(rows)}


def stage_code_map(folder):
    sys.path.insert(0, str(HERE.parents[1] / "code-map" / "scripts"))
    import codemap
    graph = json.loads((folder / "graph.json").read_text(encoding="utf-8"))
    m = codemap.Map(graph)
    between = defaultdict(int)
    for a, b in graph["imports"]:
        ga, gb = codemap.group_of(m.modules[a]), codemap.group_of(m.modules[b])
        if ga != gb and not m.is_test(a):
            between[(ga, gb)] += 1
    weight = Counter()
    for (a, b), n in between.items():
        weight[a] += n
        weight[b] += n
    keep = {g for g, _ in weight.most_common(22)}
    pairs = {}
    for (a, b), n in between.items():
        if a in keep and b in keep:
            key = tuple(sorted((a, b)))
            pairs[key] = (pairs.get(key, (0, 0))[0] + n, pairs.get(key, (0, 0))[1] + 1)
    edges = [(a, b, n, ways == 2, f"{a} ↔ {b}: {n} imports" + (", in both directions" if ways == 2 else "")) for (a, b), (n, ways) in pairs.items()]
    prod = [i for i in range(len(m.modules)) if not m.is_test(i)]
    fan_in = sorted(((m.modules[i], len([s for s in m.inc[i] if not m.is_test(s)]), None) for i in prod), key=lambda r: -r[1])[:15]
    shared = sorted(((name, len({codemap.group_of(p) for p, _ in refs["write"]}), None) for name, refs in graph["tables"].items()), key=lambda r: -r[1])
    shared = [r for r in shared if r[1] > 1][:12]
    declared = {(r["file"], r["line"], r["method"]) for r in graph["routes"]}
    bare = {(r["file"], r["line"], r["method"]) for r in graph["routes"] if not r["middleware"]}
    meta = graph["meta"]
    parts = [tiles([("Source files", len(m.modules), f"{len(prod)} outside tests"), ("Routes", len(declared), f"{len(bare)} with no router-level or inline middleware"),
                    ("Tables", len(graph["tables"]), f"{len(shared)} written from more than one folder"), ("Import cycles", len(m.cycles()), ""),
                    ("Call edges", len(graph["calls"]), f"engine: {meta['engine']}")]),
             graph_svg("Dependencies between folders", [(g, g.replace("/src/", "/"), None) for g in sorted(keep)], edges,
                       "Line weight is the number of imports. A highlighted line means the two folders import each other, which a clean layering does not have."),
             bars("Most depended-on files", fan_in, max((r[1] for r in fan_in), default=0), " files"),
             bars("Tables written from several folders", shared, max((r[1] for r in shared), default=0), " folders")]
    document = "\n\n".join((folder / name).read_text(encoding="utf-8") for name in ("code-map.md", "entry-points.md", "data.md", "modules.md", "frontend.md") if (folder / name).exists())
    document = re.sub(r"^# ", "## ", document, flags=re.M)
    return "".join(parts), document, f"commit {meta['commit'][:12] or 'unknown'} · built {meta['built']}"


STAGES = {"review": stage_review, "conflicts": stage_conflicts, "plan": stage_plan, "tickets": stage_tickets,
          "dispatch": stage_dispatch, "rereview": stage_rereview}


def find_source(stage, base):
    if stage == "review":
        merged = base / "design-review.md"
        lens = [base / f"design-review-{l}.md" for l in sc.LENSES if (base / f"design-review-{l}.md").exists()]
        return [merged] if merged.exists() else lens
    if stage == "rereview":
        return sorted(base.glob("design-rereview-*.md"))[-1:]
    name = {"conflicts": "design-review-conflicts.md", "plan": "action-plan.md", "tickets": "tickets.md", "dispatch": "dispatch.md"}[stage]
    return [base / name] if (base / name).exists() else []


# ---------- page shell ----------

STYLE = """
/* layout: an audit report. A narrow summary band of figures and charts, then the full document in folding sections. */
:root{--paper:#f5f6f8;--surface:#ffffff;--ink:#141a22;--ink-2:#4a5361;--ink-3:#7b8492;--rule:#dfe3e9;--accent:#2a78d6;--accent-soft:#cde2fb;
--critical:#d03b3b;--serious:#ec835a;--warning:#fab219;--good:#0ca30c;--chip-ink:#141a22;
--display:"IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif;--body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#12151a;--surface:#1a1e25;--ink:#f1f3f6;--ink-2:#bcc3ce;--ink-3:#8a93a1;--rule:#2c323c;--accent:#3987e5;--accent-soft:#1c3558;--chip-ink:#12151a;color-scheme:dark}}
:root[data-theme="dark"]{--paper:#12151a;--surface:#1a1e25;--ink:#f1f3f6;--ink-2:#bcc3ce;--ink-3:#8a93a1;--rule:#2c323c;--accent:#3987e5;--accent-soft:#1c3558;--chip-ink:#12151a;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 var(--body)}
.page{max-width:1120px;margin:0 auto;padding-inline:16px;padding-block:28px 64px;display:flex;flex-direction:column;gap:28px}
header.top h1{font:600 2.1rem/1.1 var(--display);margin:0 0 6px;text-wrap:balance;letter-spacing:-.01em}
header.top p{margin:0;color:var(--ink-2)}
.eyebrow{font:500 .72rem/1 var(--mono);letter-spacing:.09em;text-transform:uppercase;color:var(--ink-3);margin-bottom:10px}
.summary{display:flex;flex-direction:column;gap:20px}
header.top h1 code{font-size:.8em}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:14px 16px}
.tile-value{font:600 1.7rem/1.1 var(--display);font-variant-numeric:tabular-nums}
.tile-label{font-size:.82rem;color:var(--ink-2);margin-top:4px}
.tile-note{font-size:.78rem;color:var(--ink-3);margin-top:2px}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:20px;align-items:start}
.chart{margin:0;min-width:0}
.chart.graph{grid-column:1/-1}
figcaption{font:600 .95rem/1.3 var(--display);letter-spacing:.01em;margin-bottom:8px}
.chart-note,.legend{font-size:.8rem;color:var(--ink-3);margin:0 0 10px;max-width:65ch}
.bars{display:flex;flex-direction:column;gap:6px}
.bar-row{display:grid;grid-template-columns:minmax(0,38%) minmax(0,1fr) auto;gap:10px;align-items:center;font-size:.82rem}
.bar-label{color:var(--ink-2);overflow-wrap:anywhere}
.bar-track{height:10px;background:var(--rule);border-radius:2px;position:relative}
.bar-track.plain{background:none;border-top:1px solid var(--rule);height:1px;margin-block:6px}
.bar-fill{height:100%;background:var(--accent);border-radius:0 4px 4px 0}
.bar-value{font-variant-numeric:tabular-nums;color:var(--ink);min-width:3.2em;text-align:right;white-space:nowrap}
.bar-value.wide{min-width:8.5em}
.link{position:absolute;top:-2px;height:3px;background:var(--accent-soft)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;border:2px solid var(--paper)}
.bar-track .dot{position:absolute;top:-6px;margin-left:-5px}
.dot.before{background:var(--ink-3)}.dot.after{background:var(--accent)}
.legend .dot{vertical-align:-1px;margin:0 4px 0 10px}
.counts{display:flex;flex-wrap:wrap;gap:8px 16px}
.count{display:flex;align-items:center;gap:8px}
.count-n{font:600 1.05rem var(--display);font-variant-numeric:tabular-nums}
.chip{display:inline-block;font:500 .72rem/1.5 var(--mono);padding:0 7px;border-radius:3px;border:1px solid var(--rule);color:var(--ink-2);white-space:nowrap}
.chip.critical{background:var(--critical);border-color:var(--critical);color:#fff}
.chip.serious{background:var(--serious);border-color:var(--serious);color:var(--chip-ink)}
.chip.warning{background:var(--warning);border-color:var(--warning);color:var(--chip-ink)}
.graph-wrap{overflow-x:auto;background:var(--surface);border:1px solid var(--rule);border-radius:6px}
.graph-wrap svg{display:block;width:100%;min-width:640px;max-width:920px;margin:0 auto;height:auto}
.edge{stroke:var(--ink-3);opacity:.35}.edge.flagged{stroke:var(--serious);opacity:.9}
.node{fill:var(--accent);stroke:var(--surface);stroke-width:2}
svg text{font:11px var(--mono);fill:var(--ink-2)}
.tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.tools input{flex:1 1 240px;min-width:0}
input[type=search]{font:inherit;padding:7px 10px;border:1px solid var(--rule);border-radius:4px;background:var(--surface);color:var(--ink)}
button{font:inherit;padding:7px 12px;border:1px solid var(--rule);border-radius:4px;background:var(--surface);color:var(--ink);cursor:pointer}
button:hover{border-color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
h2.part{font:600 1.5rem/1.2 var(--display);margin:28px 0 4px;padding-top:18px;border-top:2px solid var(--ink)}
details.section{border-top:1px solid var(--rule)}
details.section>summary{cursor:pointer;padding:12px 0;list-style-position:outside}
details.section>summary h3{display:inline;font:600 1.15rem/1.3 var(--display);margin:0}
details.item{background:var(--surface);border:1px solid var(--rule);border-radius:6px;margin:8px 0}
details.item>summary{cursor:pointer;padding:10px 12px;display:flex;flex-wrap:wrap;gap:8px;align-items:baseline}
details.item:target{border-color:var(--accent)}
.id{font:500 .82rem var(--mono);color:var(--accent)}
.item-title{font-weight:600;min-width:0;overflow-wrap:anywhere}
details.item>.body{padding:0 14px 12px;border-top:1px solid var(--rule)}
.body{min-width:0}
.body p,.body li{max-width:78ch}
.body h4,.body h5{font:600 1rem var(--display);margin:18px 0 6px}
a{color:var(--accent)}a.ref{font-family:var(--mono);font-size:.9em;text-decoration:none}a.ref:hover{text-decoration:underline}
code{font:.86em var(--mono);background:var(--accent-soft);padding:1px 4px;border-radius:3px;overflow-wrap:anywhere}
pre{background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:12px;overflow-x:auto}
pre code{background:none;padding:0}
.table-wrap{overflow-x:auto;margin:10px 0}
.table-wrap .filter{margin-bottom:6px;width:min(100%,320px)}
table{border-collapse:collapse;font-size:.84rem;min-width:100%}
th,td{text-align:left;vertical-align:top;padding:6px 10px;border-bottom:1px solid var(--rule)}
th{font:600 .74rem var(--mono);letter-spacing:.04em;text-transform:uppercase;color:var(--ink-3);cursor:pointer;white-space:nowrap;background:var(--paper);position:sticky;top:0}
td{font-variant-numeric:tabular-nums}
footer{color:var(--ink-3);font-size:.8rem;border-top:1px solid var(--rule);padding-top:14px}
@media (max-width:560px){.bar-row{grid-template-columns:1fr auto}.bar-label{grid-column:1/-1}}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
"""

SCRIPT = """
(function(){
  function openFor(id){var el=document.getElementById(id);if(!el)return;for(var p=el;p;p=p.parentElement){if(p.tagName==='DETAILS')p.open=true}el.scrollIntoView()}
  if(location.hash)openFor(location.hash.slice(1));
  window.addEventListener('hashchange',function(){openFor(location.hash.slice(1))});
  document.querySelectorAll('.table-wrap .filter').forEach(function(input){
    var rows=input.parentElement.querySelectorAll('tbody tr');
    input.addEventListener('input',function(){var q=input.value.toLowerCase();rows.forEach(function(r){r.hidden=q&&r.textContent.toLowerCase().indexOf(q)<0})})});
  document.querySelectorAll('th').forEach(function(th){th.addEventListener('click',function(){
    var body=th.closest('table').tBodies[0],i=th.cellIndex,dir=th.dataset.dir==='1'?-1:1;th.dataset.dir=dir===1?'1':'0';
    Array.prototype.slice.call(body.rows).sort(function(a,b){var x=a.cells[i]?a.cells[i].textContent.trim():'',y=b.cells[i]?b.cells[i].textContent.trim():'',n=parseFloat(x),m=parseFloat(y);
      return dir*((isNaN(n)||isNaN(m))?x.localeCompare(y):n-m)}).forEach(function(r){body.appendChild(r)})})});
  var find=document.getElementById('find-entry'),items=document.querySelectorAll('details.item');
  if(find)find.addEventListener('input',function(){var q=find.value.toLowerCase();items.forEach(function(d){
    var hit=!q||d.dataset.search.indexOf(q)>=0||d.textContent.toLowerCase().indexOf(q)>=0;d.hidden=!hit;if(q&&hit)for(var p=d.parentElement;p;p=p.parentElement){if(p.tagName==='DETAILS')p.open=true}})});
  function all(open){document.querySelectorAll('details.section').forEach(function(d){d.open=open})}
  var a=document.getElementById('open-all'),c=document.getElementById('close-all');
  if(a)a.addEventListener('click',function(){all(true)});if(c)c.addEventListener('click',function(){all(false)});
})();
"""


def build(stage, base, source, name):
    if stage == "code-map":
        folder = Path(source) if source else base / "code-map"
        if not (folder / "graph.json").exists():
            sys.exit(f"error: no code map at {folder}; run `codemap.py build` first")
        dashboard, text, origin = stage_code_map(folder)
        sources = [folder / "graph.json"]
    else:
        sources = [Path(source)] if source else find_source(stage, base)
        if not sources or not all(p.exists() for p in sources):
            sys.exit(f"error: nothing to render for `{stage}` under {base}")
        text = "\n\n".join((f"# Lens: {p.stem.split('-')[-1]}\n\n" if len(sources) > 1 else "") + p.read_text(encoding="utf-8") for p in sources)
        dashboard, _ = STAGES[stage](text)
        origin = ", ".join(p.name for p in sources)
    known = set()
    for level, title, _ in split_sections(text):
        entry = ITEM_HEAD.match(title) if level >= 2 else None
        if entry:
            known.add(entry.group(1))
    first_title = next((t for level, t, _ in split_sections(text) if level == 1 and not t.lower().startswith("lens:")), "")
    body = render_document(re.sub(r"\A\s*# [^\n]*\n", "", text, count=1) if first_title else text, known)
    title = f"{name} {TITLES[stage]}".strip()
    tools = ('<div class="tools">' + ('<input id="find-entry" type="search" placeholder="Find an entry by id, severity or words" aria-label="Find an entry">' if known else "")
             + '<button id="open-all" type="button">Open all sections</button><button id="close-all" type="button">Close all sections</button></div>')
    fonts = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@600&display=swap">'
    inner = (f"<title>{esc(title)}</title>\n{fonts}\n<style>{STYLE}</style>\n<div class=\"page\">\n<header class=\"top\"><div class=\"eyebrow\">{esc(TITLES[stage])} · {esc(origin)}</div>"
             f"<h1>{inline(first_title or title, set())}</h1></header>\n<section class=\"summary\" aria-label=\"Summary\">{wrap_charts(dashboard)}</section>\n"
             f"<main>{tools}\n{body}</main>\n<footer>Rendered from {esc(origin)} by page.py. Figures are computed from the document below; the document is the record.</footer>\n</div>\n<script>{SCRIPT}</script>")
    return title, inner


def wrap_charts(dashboard):
    """tiles stay full width; the charts that follow share a grid."""
    head, _, rest = dashboard.partition("</section>") if dashboard.startswith('<section class="tiles">') else ("", "", dashboard)
    tiles_html = head + "</section>" if head else ""
    return tiles_html + (f'<div class="charts">{rest}</div>' if rest.strip() else "")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["code-map"] + list(STAGES))
    parser.add_argument("base")
    parser.add_argument("--source")
    parser.add_argument("--out")
    parser.add_argument("--name")
    args = parser.parse_args()
    base = Path(args.base).resolve()
    name = args.name if args.name is not None else (base.parents[1].name if base.name == "remediation" and base.parent.name == "docs" else "")
    title, inner = build(args.stage, base, args.source, name)
    out = Path(args.out) if args.out else base / "pages"
    (out / "artifact").mkdir(parents=True, exist_ok=True)
    full = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + inner.replace("<div class=\"page\">", "</head>\n<body>\n<div class=\"page\">", 1) + "\n</body>\n</html>\n")
    (out / f"{args.stage}.html").write_text(full, encoding="utf-8")
    (out / "artifact" / f"{args.stage}.html").write_text(inner + "\n", encoding="utf-8")
    print(f"page:     {out / (args.stage + '.html')}")
    print(f"artifact: {out / 'artifact' / (args.stage + '.html')}   (title: {title})")


if __name__ == "__main__":
    main()
