"""Read measurement rows and render the savings table."""
from harness.minify.lib.churn import CHURN_LINES, CHURN_FRACTION
from harness.minify.lib.estimate import load_k, _r
from harness.minify.lib.events import read

def measures(paths):
    rows = []
    for p in paths:
        for r in read(p):
            if r.get("k") == "measure":
                r.setdefault("session", getattr(p, "stem", str(p)))
                rows.append(r)
    return rows

def _usable(r):
    """Check that a row has all required fields and was successfully formatted."""
    return (bool(r.get("formatter_ok")) and
            r.get("tok_fmt") is not None and
            r.get("file") is not None and
            r.get("ext") is not None and
            r.get("tok_min") is not None)

def _churn_heavy(r):
    """FIX 6: same threshold format_turn.py's turn-end warning uses (imported from
    lib/churn.py so there is one definition, not two that can drift). A row this
    heavy describes reformatting the file more than it describes what the session
    emitted -- e.g. a one-character edit to a committed minified bundle, which
    makes the Stop hook reformat the whole thing and would otherwise print a
    fictional "saved 98%" headline. Missing/None fields (older rows, predating the
    lines_fmt field) are treated as not-heavy rather than unknown-and-excluded."""
    outside = r.get("churn_outside")
    nlines = r.get("lines_fmt")
    if not outside or not nlines:
        return False
    return outside > CHURN_LINES or outside > CHURN_FRACTION * nlines

def dedupe(rows):
    """Last measurement per (session, file), in first-appearance order.
    Rows that were never formatted are ignored. When multiple rows have the same
    turn, the later one in input order wins (via >= comparison)."""
    keep, order = {}, []
    for r in rows:
        if not _usable(r):
            continue
        key = (r.get("session"), r["file"])
        if key not in keep:
            order.append(key)
            keep[key] = r
        elif r.get("turn", 0) >= keep[key].get("turn", 0):
            keep[key] = r
    return [keep[k] for k in order]

def _pct(saved, base):
    return f"{_r(100 * saved / base)}%" if base else "-"

def by_lang(rows):
    groups = {}
    for r in rows:
        if not _usable(r) or _churn_heavy(r):
            continue
        g = groups.setdefault(r["ext"], {"ext": r["ext"], "tok_min": 0, "tok_fmt": 0, "files": 0})
        g["tok_min"] += r["tok_min"]
        g["tok_fmt"] += r["tok_fmt"]
        g["files"] += 1
    for g in groups.values():
        g["saved"] = g["tok_fmt"] - g["tok_min"]
    return sorted(groups.values(), key=lambda g: -(g["saved"] / g["tok_fmt"] if g["tok_fmt"] else 0))

def render(rows, scope, chars=False, turns=False):
    """`turns=True` lists every per-turn measurement row for a file touched more
    than once. The total, headline and (if requested) char counts are always
    computed from `dedupe(rows)` regardless of `turns` -- summing every row would
    count a multi-turn file's tokens once per turn (FIX 5). A churn-heavy row (FIX
    6: formatting rewrote far more than the session emitted, e.g. a one-character
    edit to a committed minified bundle) is still listed and marked inline, but is
    excluded from that same total so it cannot inflate the headline."""
    usable = [r for r in rows if _usable(r)]
    deduped = dedupe(usable)
    if not deduped:
        return f"{scope}\n\n  no measurements yet\n"
    shown = usable if turns else deduped
    clean = [r for r in deduped if not _churn_heavy(r)]
    k, calibrated = load_k()
    w = max(len(r["file"]) for r in shown)
    lines = [scope, ""]
    if turns:
        lines.append("  per-turn rows (every measurement; totals below are deduped by file):")
    lines.append(f"  {'file'.ljust(w)}  tok_min  tok_fmt    saved")
    for r in sorted(shown, key=lambda r: (r.get("session", ""), r["file"], r.get("turn", 0))):
        saved = r["tok_fmt"] - r["tok_min"]
        flag = "  [churn-heavy, excluded from total]" if _churn_heavy(r) else ""
        lines.append(f"  {r['file'].ljust(w)}  {r['tok_min']:7}  {r['tok_fmt']:7}  {saved:7} {_pct(saved, r['tok_fmt']):>5}{flag}")
    lines.append("  " + "-" * (w + 32))
    tmin = sum(r["tok_min"] for r in clean)
    tfmt = sum(r["tok_fmt"] for r in clean)
    saved = tfmt - tmin
    lines.append(f"  {'total'.ljust(w)}  {tmin:7}  {tfmt:7}  {saved:7} {_pct(saved, tfmt):>5}")
    excluded = len(deduped) - len(clean)
    if excluded:
        lines.append(f"  ({excluded} file(s) excluded above: formatting churn exceeded the "
                      f"threshold -- {CHURN_LINES} lines or {int(CHURN_FRACTION * 100)}% of the file)")
    lines.append("")
    lines.append(f"SAVED {_pct(saved, tfmt)} on emitted code")
    if chars:
        cmin = sum(r.get("chars_min") or 0 for r in clean)
        cfmt = sum(r.get("chars_fmt") or 0 for r in clean)
        lines.append(f"chars: {cmin:,} -> {cfmt:,}  ({_pct(cfmt - cmin, cfmt)})")
    lines.append(f"estimator: local regex-class, k={k}, "
                 f"{'calibrated' if calibrated else 'uncalibrated'}, ratio-stable")
    lines.append("measures the whole file as left on disk, not just what this turn emitted; "
                 "failed edits and re-reads are not netted out")
    return "\n".join(lines) + "\n"
