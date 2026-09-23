"""Did formatting rewrite lines the session never touched?

Two diffs, both expressed in `mine` coordinates:
  my_lines  = lines of `mine` that differ from the git pre-image
  fmt_lines = lines of `mine` that formatting rewrote
  churn_outside = |fmt_lines - my_lines|
"""
import difflib, subprocess

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
    """Content of `rel` at HEAD, or "" when untracked, unborn, or not a repo."""
    try:
        p = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=root,
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeDecodeError):
        return ""
    return p.stdout if p.returncode == 0 else ""
