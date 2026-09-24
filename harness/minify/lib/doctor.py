# harness/minify/lib/doctor.py
"""Which languages are safe to minify in this project, and is the repo formatter-clean?"""
import os, subprocess
from harness.minify.lib.classes import COLLAPSE, DENSE
from harness.minify.lib.detect import detect
from harness.minify.lib.unsafe import load as load_unsafe

MAX_CHECK = 200
CLEAN_PROBE_EXT = "ts"

def _tracked(cwd, exts):
    """(files, tracked_total) for tracked paths matching exts, files capped at MAX_CHECK
    and returned as absolute paths -- the probe formatter is run via subprocess with no
    cwd=, so a relative path would depend on the calling process's own working directory
    instead of the project root. None means git could not answer (no repo, or an error)."""
    pats = [f"*.{e}" for e in exts]
    try:
        p = subprocess.run(["git", "ls-files", "-z", "--"] + pats, cwd=cwd,
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    rel = [f for f in p.stdout.split("\0") if f]
    files = [os.path.join(cwd, f) for f in rel[:MAX_CHECK]]
    return files, len(rel)

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

    repo_clean, checked, truncated, tracked_total = None, 0, False, 0
    probe = detect(cwd, CLEAN_PROBE_EXT)
    if probe is not None and probe.per_file:
        # FIX 2: hand the probe only the extensions it genuinely claims, not every
        # COLLAPSE|DENSE extension -- real prettier errors on a tracked .sh or .py,
        # which made check_many's single batch invocation report the whole sample
        # dirty even when every file the probe can actually parse was clean. An
        # extension counts as "the probe's own" when detect() independently returns
        # the identical formatter for it (same .name).
        probe_exts = sorted(e for e in (COLLAPSE | DENSE)
                             if (df := detect(cwd, e)) is not None and df.name == probe.name)
        tracked = _tracked(cwd, probe_exts)
        if tracked is not None:
            files, tracked_total = tracked
            checked = len(files)
            truncated = tracked_total > checked
            if files:
                ok, _ = probe.check_many(files)
                if not ok:
                    # A dirty sample is proof at any size: one non-conforming file is
                    # enough to know the repo is not formatter-clean.
                    repo_clean = False
                elif truncated:
                    # A clean sample is NOT proof about the unchecked remainder --
                    # stay in the "could not be determined" state rather than claim True.
                    repo_clean = None
                else:
                    repo_clean = True
    return {"safe": safe, "blocked": blocked, "formatters": formatters,
            "repo_clean": repo_clean, "checked": checked,
            "truncated": truncated, "tracked_total": tracked_total}

def one_line(v):
    safe = ",".join(v["safe"]) or "none"
    blocked = ",".join(sorted(v["blocked"])) or "none"
    if v["repo_clean"] is True:
        rule = "repo formatter-clean: minify new and existing files"
    elif v["repo_clean"] is False:
        rule = "repo NOT formatter-clean: minify new files only"
    elif v["truncated"]:
        rule = (f"checked {v['checked']} of {v['tracked_total']}, "
                 "cleanliness unknown: minify new files only")
    else:
        rule = "cleanliness unknown: minify new files only"
    return f"minify-harness: safe={safe} | blocked={blocked} | {rule}"
