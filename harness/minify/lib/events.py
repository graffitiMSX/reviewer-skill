"""NDJSON event log, per-session turn counter, and the active output style."""
import json, os, re
from pathlib import Path

def _home(home=None):
    return Path(home) if home else Path.home()

def project_slug(cwd):
    """Mirror Claude Code's own project directory naming."""
    return re.sub(r"[^A-Za-z0-9]+", "-", os.path.abspath(cwd))

def harness_dir(cwd, home=None):
    return _home(home) / ".claude" / "minify-harness" / project_slug(cwd)

def log_path(cwd, session_id, home=None):
    return harness_dir(cwd, home) / f"{session_id}.ndjson"

def append(cwd, session_id, obj, home=None):
    p = log_path(cwd, session_id, home)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, separators=(",", ":")) + "\n")

def read(path):
    """Read an NDJSON log, skipping malformed lines rather than failing."""
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return rows

def read_session(cwd, session_id, home=None):
    return read(log_path(cwd, session_id, home))

def all_logs(cwd, home=None):
    d = harness_dir(cwd, home)
    return sorted(d.glob("*.ndjson"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []

def latest_session(cwd, home=None):
    logs = all_logs(cwd, home)
    return logs[-1] if logs else None

def _state_path(cwd, session_id, home=None):
    return harness_dir(cwd, home) / f"{session_id}.state.json"

def current_turn(cwd, session_id, home=None):
    try:
        with open(_state_path(cwd, session_id, home), encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                turn = data.get("turn")
                if turn is not None:
                    return int(turn)
    except (OSError, ValueError, TypeError):
        pass
    return 1

def bump_turn(cwd, session_id, home=None):
    n = current_turn(cwd, session_id, home) + 1
    p = _state_path(cwd, session_id, home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"turn": n}))
    return n

def active_style(cwd, home=None):
    """Read outputStyle from the settings chain; later files win."""
    paths = [_home(home) / ".claude" / "settings.json",
             Path(cwd) / ".claude" / "settings.json",
             Path(cwd) / ".claude" / "settings.local.json"]
    style = None
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    v = data.get("outputStyle")
                    if v:
                        style = v
        except (OSError, ValueError, AttributeError, TypeError):
            continue
    return style
