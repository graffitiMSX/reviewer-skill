"""Extensions this project must not minify, because their formatter is missing."""
import datetime as dt, json
from pathlib import Path
from harness.minify.lib.events import harness_dir

def path(cwd, home=None):
    return harness_dir(cwd, home) / "unsafe.json"

def _read(cwd, home=None):
    try:
        with open(path(cwd, home)) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}

def load(cwd, home=None):
    return set(_read(cwd, home))

def mark(cwd, ext, reason, home=None):
    d = _read(cwd, home)
    d[ext] = {"reason": reason, "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    p = path(cwd, home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, sort_keys=True))

def clear(cwd, ext, home=None):
    d = _read(cwd, home)
    if ext not in d:
        return False
    del d[ext]
    path(cwd, home).write_text(json.dumps(d, indent=1, sort_keys=True))
    return True
