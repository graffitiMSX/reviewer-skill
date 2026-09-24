"""Idempotent hook entries in a Claude Code settings.json. Ours are identified by MARKER."""
import json, os, shutil, tempfile

MARKER = "--minify-harness"
ENTRIES = (("SessionStart", "*", "session_doctor.py", 10),
           ("PostToolUse", "Write|Edit", "log_write.py", 10),
           ("Stop", "*", "format_turn.py", 60))


class SettingsError(Exception):
    """settings.json exists but is not usable (unparseable, or valid JSON that is
    not an object). Never silently discarded."""


def _load(path):
    try:
        with open(path) as fh:
            text = fh.read()
    except FileNotFoundError:
        return {}  # no file yet -- a legitimate green field
    # Anything other than "the file is not there yet" (permission denied, a
    # directory where the file should be, ...) must not be mistaken for that --
    # narrowed from a blanket `except OSError` (minor fix).
    try:
        data = json.loads(text)
    except ValueError as e:
        raise SettingsError(f"{path} exists but is not valid JSON ({e}); refusing to touch it") from e
    if not isinstance(data, dict):
        raise SettingsError(
            f"{path} exists but its top level is a JSON {type(data).__name__}, not an "
            "object; refusing to touch it")
    return data


def _save(path, data):
    """Write `data` to `path` atomically: a full write to a temp file in the same
    directory, then os.replace() into place. A failure mid-write (ENOSPC, a signal)
    leaves the temp file half-written and the real settings.json untouched, instead
    of truncating the user's live config in place (FIX 8)."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".minify-harness-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
    Raises SettingsError, touching nothing, if settings_path exists but is not valid JSON.
    Takes a `.minify-bak` snapshot of the file as it stood right before this write,
    the same safety net `patch` gives on first install (FIX 8; previously absent here)."""
    data = _load(settings_path)
    if os.path.exists(settings_path) and _has_marker(data):
        # Only when there is actually something to remove -- mirrors patch()'s own
        # first_install gate, so a no-op unpatch on an already-clean file does not
        # spuriously overwrite (or create) a backup of nothing changing.
        shutil.copy2(settings_path, settings_path + ".minify-bak")
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
