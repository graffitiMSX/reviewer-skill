"""Idempotent hook entries in a Claude Code settings.json. Ours are identified by MARKER."""
import json, os, shutil

MARKER = "--minify-harness"
ENTRIES = (("SessionStart", "*", "session_doctor.py", 10),
           ("PostToolUse", "Write|Edit", "log_write.py", 10),
           ("Stop", "*", "format_turn.py", 60))


class SettingsError(Exception):
    """settings.json exists but is not valid JSON. Never silently discarded."""


def _load(path):
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError:
        return {}  # no file yet -- a legitimate green field
    try:
        return json.loads(text)
    except ValueError as e:
        raise SettingsError(f"{path} exists but is not valid JSON ({e}); refusing to touch it") from e


def _save(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def _has_marker(data):
    hooks = data.get("hooks") or {}
    return any(MARKER in h.get("command", "")
               for groups in hooks.values() for g in groups for h in g.get("hooks", []))


def patch(settings_path, root):
    """Add or refresh our three hook entries. Safe to run repeatedly, and safe to
    run again after `root` changes (e.g. the checkout moved) -- a stale command is
    replaced in place rather than left stranded alongside a new one. Raises
    SettingsError, touching nothing, if settings_path exists but is not valid JSON."""
    data = _load(settings_path)
    first_install = os.path.exists(settings_path) and not _has_marker(data)
    if first_install:
        shutil.copy2(settings_path, settings_path + ".minify-bak")
    hooks = data.setdefault("hooks", {})
    changed = []
    for event, matcher, script, timeout in ENTRIES:
        command = f"python3 {os.path.join(root, 'hooks', script)} {MARKER}"
        groups = hooks.setdefault(event, [])
        existing = next((h for g in groups for h in g.get("hooks", [])
                          if MARKER in h.get("command", "") and script in h.get("command", "")), None)
        if existing is not None:
            if existing.get("command") != command:
                existing["command"] = command
                existing["timeout"] = timeout
                changed.append(event)
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
    """Remove every hook entry containing MARKER, and any group or event left empty.
    Raises SettingsError, touching nothing, if settings_path exists but is not valid JSON."""
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
