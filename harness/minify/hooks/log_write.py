#!/usr/bin/env python3
"""PostToolUse hook. Appends one row per Write/Edit. Never blocks, never reads the tool result."""
import datetime as dt, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from harness.minify.lib.classes import classify
from harness.minify.lib.estimate import chars, estimate, load_k
from harness.minify.lib import events as E

PAYLOAD_KEY = {"Write": "content", "Edit": "new_string"}

def payload_of(tool_name, tool_input):
    key = PAYLOAD_KEY.get(tool_name)
    if not key or not isinstance(tool_input, dict):
        return None
    v = tool_input.get(key)
    return v if isinstance(v, str) else None

def main(stdin_text, home=None):
    try:
        d = json.loads(stdin_text or "")
        cwd = d["cwd"]
        tool = d.get("tool_name", "")
        tool_input = d.get("tool_input") or {}
        session = d.get("session_id") or "unknown"
    except (ValueError, KeyError, TypeError):
        return 0
    try:
        payload = payload_of(tool, tool_input)
        raw = tool_input.get("file_path")
        if payload is None or not isinstance(raw, str) or not raw:
            return 0
        rel = os.path.relpath(raw, cwd) if os.path.isabs(raw) else raw
        cls = classify(rel)
        if cls == "exclude":
            return 0
        k, _ = load_k()
        E.append(cwd, session, {
            "k": "write",
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "turn": E.current_turn(cwd, session, home),
            "tool": tool,
            "file": rel,
            "ext": rel.rsplit(".", 1)[1].lower() if "." in rel else "",
            "class": cls,
            "chars": chars(payload),
            "tok": estimate(payload, k),
            "style": E.active_style(cwd, home),
        }, home=home)
    except Exception:
        return 0
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.stdin.read()))
