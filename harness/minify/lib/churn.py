"""Did formatting rewrite lines the session never touched?

Two diffs, both expressed in `mine` coordinates:
  my_lines  = lines of `mine` that differ from the git pre-image
  fmt_lines = lines of `mine` that formatting rewrote
  churn_outside = |fmt_lines - my_lines|
"""
import difflib, subprocess

# Single definition shared by hooks/format_turn.py (the turn-end warning) and
# lib/report.py (excluding a churn-heavy row from the aggregate and headline) --
# two independent copies of these numbers could drift out of sync (FIX 6).
CHURN_LINES = 20
CHURN_FRACTION = 0.3

def _ops(a, b):
    return difflib.SequenceMatcher(None, a.splitlines(), b.splitlines()).get_opcodes()

def changed_a(a, b):
    """1-based line numbers in `a` that were replaced or deleted."""
    out = set()
    for tag, i1, i2, _j1, _j2 in _ops(a, b):
        if tag in ("replace", "delete"):
            out.update(range(i1 + 1, i2 + 1))
    return out

def changed_b(a, b):
    """1-based line numbers in `b` that were replaced or inserted."""
    out = set()
    for tag, _i1, _i2, j1, j2 in _ops(a, b):
        if tag in ("replace", "insert"):
            out.update(range(j1 + 1, j2 + 1))
    return out

def churn_outside(pre, mine, fmt):
    """Count lines formatting rewrote that the session had not itself changed."""
    return len(changed_a(mine, fmt) - changed_b(pre, mine))

def git_pre_image(root, rel):
    """Content of `rel` at HEAD; "" when untracked, unborn, or not a repo (git ran
    and told us there is no such blob); None when retrieval failed outright (git
    could not be invoked or its output could not be read: missing binary, an
    embedded NUL, undecodable content). Distinguishing the two matters -- a
    transient failure must not silently read as "new file" the way both used to
    collapse to the same "" (minor, FIX 6 ledger note)."""
    try:
        p = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=root,
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeDecodeError):
        return None
    return p.stdout if p.returncode == 0 else ""
