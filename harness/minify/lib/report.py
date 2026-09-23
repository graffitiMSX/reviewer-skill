"""Read measurement rows and render the savings table."""
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
        if not _usable(r):
            continue
        g = groups.setdefault(r["ext"], {"ext": r["ext"], "tok_min": 0, "tok_fmt": 0, "files": 0})
        g["tok_min"] += r["tok_min"]
        g["tok_fmt"] += r["tok_fmt"]
        g["files"] += 1
    for g in groups.values():
        g["saved"] = g["tok_fmt"] - g["tok_min"]
    return sorted(groups.values(), key=lambda g: -(g["saved"] / g["tok_fmt"] if g["tok_fmt"] else 0))

def render(rows, scope, chars=False, turns=False):
    shown = rows if turns else dedupe(rows)
    shown = [r for r in shown if _usable(r)]
    if not shown:
        return f"{scope}\n\n  no measurements yet\n"
    k, calibrated = load_k()
    w = max(len(r["file"]) for r in shown)
    lines = [scope, "", f"  {'file'.ljust(w)}  tok_min  tok_fmt    saved"]
    tmin = tfmt = 0
    for r in sorted(shown, key=lambda r: (r.get("session", ""), r["file"], r.get("turn", 0))):
        saved = r["tok_fmt"] - r["tok_min"]
        tmin += r["tok_min"]
        tfmt += r["tok_fmt"]
        lines.append(f"  {r['file'].ljust(w)}  {r['tok_min']:7}  {r['tok_fmt']:7}  {saved:7} {_pct(saved, r['tok_fmt']):>5}")
    lines.append("  " + "-" * (w + 32))
    saved = tfmt - tmin
    lines.append(f"  {'total'.ljust(w)}  {tmin:7}  {tfmt:7}  {saved:7} {_pct(saved, tfmt):>5}")
    lines.append("")
    lines.append(f"SAVED {_pct(saved, tfmt)} on emitted code")
    if chars:
        cmin = sum(r.get("chars_min") or 0 for r in shown)
        cfmt = sum(r.get("chars_fmt") or 0 for r in shown)
        lines.append(f"chars: {cmin:,} -> {cfmt:,}  ({_pct(cfmt - cmin, cfmt)})")
    lines.append(f"estimator: local regex-class, k={k}, "
                 f"{'calibrated' if calibrated else 'uncalibrated'}, ratio-stable")
    lines.append("counts emitted code only: failed edits and re-reads are not netted out")
    return "\n".join(lines) + "\n"
