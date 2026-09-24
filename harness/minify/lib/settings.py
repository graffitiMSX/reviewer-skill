"""Idempotent hook entries in a Claude Code settings.json. Ours are identified by MARKER."""
import json, os, shutil

MARKER = "minify/hooks/"
ENTRIES = (("SessionStart", "*", "session_doctor.py", 10),
           ("PostToolUse", "Write|Edit", "log_write.py", 10),
           ("Stop", "*", "format_turn.py", 60))

def _load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}

def _save(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")

def patch(settings_path, root):
    """Add our three hook entries. Safe to run repeatedly."""
    data = _load(settings_path)
    if os.path.exists(settings_path):
        shutil.copy2(settings_path, settings_path + ".minify-bak")
    hooks = data.setdefault("hooks", {})
    changed = []
    for event, matcher, script, timeout in ENTRIES:
        command = f"python3 {os.path.join(root, 'hooks', script)}"
        groups = hooks.setdefault(event, [])
        if any(MARKER in h.get("command", "") and script in h.get("command", "")
               for g in groups for h in g.get("hooks", [])):
            continue
        group = next((g for g in groups if g.get("matcher") == matcher), None)
        if group is None:
            group = {"matcher": matcher, "hooks": []}
            groups.append(group)
        group["hooks"].append({"type": "command", "command": command, "timeout": timeout})
        changed.append(event)
    _save(settings_path, data)
    return changed

def unpatch(settings_path):
    """Remove every hook entry containing MARKER, and any group left empty."""
    data = _load(settings_path)
    hooks = data.get("hooks") or {}
    changed = []
    for event in list(hooks):
        groups = []
        for g in hooks[event]:
            kept = [h for h in g.get("hooks", []) if MARKER not in h.get("command", "")]
            if len(kept) != len(g.get("hooks", [])):
                changed.append(event)
            if kept:
                g["hooks"] = kept
                groups.append(g)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks and "hooks" in data:
        del data["hooks"]
    _save(settings_path, data)
    return changed
