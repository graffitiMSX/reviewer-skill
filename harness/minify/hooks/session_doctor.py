#!/usr/bin/env python3
# harness/minify/hooks/session_doctor.py
"""SessionStart hook. Injects one line saying what is safe to minify here."""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from harness.minify.lib.doctor import one_line, verdict

def main(stdin_text, home=None):
    try:
        cwd = json.loads(stdin_text or "")["cwd"]
    except (ValueError, KeyError, TypeError):
        return 0
    if not isinstance(cwd, str) or not cwd:
        return 0
    try:
        text = one_line(verdict(cwd, home=home))
    except Exception:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": text}}))
    return 0

if __name__ == "__main__":
    try:
        stdin_text = sys.stdin.read()
    except Exception:
        sys.exit(0)
    sys.exit(main(stdin_text))
