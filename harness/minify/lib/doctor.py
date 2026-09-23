# harness/minify/lib/doctor.py
"""Which languages are safe to minify in this project, and is the repo formatter-clean?"""
import subprocess
from harness.minify.lib.classes import COLLAPSE, DENSE
from harness.minify.lib.detect import detect
from harness.minify.lib.unsafe import load as load_unsafe

MAX_CHECK = 200
CLEAN_PROBE_EXT = "ts"

def _tracked(cwd, exts):
    pats = [f"*.{e}" for e in exts]
    try:
        p = subprocess.run(["git", "ls-files", "-z", "--"] + pats, cwd=cwd,
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return [f for f in p.stdout.split("\0") if f][:MAX_CHECK]

def verdict(cwd, home=None):
    blocked_exts = load_unsafe(cwd, home)
    safe, blocked, formatters = [], {}, {}
    for ext in sorted(COLLAPSE | DENSE):
        f = detect(cwd, ext)
        formatters[ext] = f.name if f else None
        if ext in blocked_exts:
            blocked[ext] = "marked unsafe in unsafe.json"
        elif f is None:
            blocked[ext] = "no formatter"
        elif not f.per_file:
            blocked[ext] = f"{f.name} is not per-file"
        else:
            safe.append(ext)

    repo_clean, checked = None, 0
    probe = detect(cwd, CLEAN_PROBE_EXT)
    if probe is not None and probe.per_file:
        files = _tracked(cwd, sorted(COLLAPSE | DENSE))
        if files:
            checked = len(files)
            ok, _ = probe.check_many(files)
            repo_clean = ok
    return {"safe": safe, "blocked": blocked, "formatters": formatters,
            "repo_clean": repo_clean, "checked": checked}

def one_line(v):
    safe = ",".join(v["safe"]) or "none"
    blocked = ",".join(sorted(v["blocked"])) or "none"
    if v["repo_clean"] is True:
        rule = "repo formatter-clean: minify new and existing files"
    elif v["repo_clean"] is False:
        rule = "repo NOT formatter-clean: minify new files only"
    else:
        rule = "cleanliness unknown: minify new files only"
    return f"minify-harness: safe={safe} | blocked={blocked} | {rule}"
