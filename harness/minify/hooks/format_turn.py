#!/usr/bin/env python3
# harness/minify/hooks/format_turn.py
"""Stop hook. Formats the files this turn touched and records both token counts."""
import datetime as dt, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from harness.minify.lib.classes import classify
from harness.minify.lib.estimate import chars, estimate, load_k
from harness.minify.lib.churn import churn_outside, git_pre_image
from harness.minify.lib.detect import detect
from harness.minify.lib import events as E, unsafe as U

CHURN_LINES = 20
CHURN_FRACTION = 0.3

def _files_this_turn(rows, turn):
    """Ordered unique files written this turn, with the tools that wrote them."""
    seen = {}
    for r in rows:
        if r.get("k") != "write" or r.get("turn") != turn:
            continue
        f = r.get("file")
        if not f:
            continue  # malformed row must not abort grouping for the rest of the turn
        seen.setdefault(f, []).append(r.get("tool", "?"))
    return seen

def _emit(messages):
    if not messages:
        return
    text = "minify-harness: " + " | ".join(messages)
    print(json.dumps({
        "systemMessage": text,
        "hookSpecificOutput": {"hookEventName": "Stop", "systemMessage": text},
    }))

def _process_file(cwd, session, turn, rel, ops, k, home, messages):
    """Measure, format, and re-measure a single file, appending its own row.

    Left to raise on any unexpected failure (a deleted-between-list-and-read race,
    a permission problem, a disk error mid-append) -- the caller guards each file
    individually so one file's exception never stops the files that follow it.
    """
    if classify(rel) == "exclude":
        return
    abspath = os.path.join(cwd, rel)
    if not os.path.isfile(abspath):
        return
    basename = os.path.basename(rel)
    ext = basename.rsplit(".", 1)[1].lower() if "." in basename else ""
    mine = Path(abspath).read_text(errors="replace")
    row = {"k": "measure",
           "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "turn": turn, "file": rel, "ext": ext, "class": classify(rel),
           "ops": ops, "style": E.active_style(cwd, home),
           "chars_min": chars(mine), "tok_min": estimate(mine, k),
           "chars_fmt": None, "tok_fmt": None,
           "churn_outside": None, "pre_image": "git:HEAD"}

    fmt = detect(cwd, ext)
    if fmt is None or not fmt.per_file:
        why = "no formatter" if fmt is None else f"{fmt.name} is not per-file"
        U.mark(cwd, ext, why, home=home)
        row["formatter"] = fmt.name if fmt else None
        row["formatter_ok"] = False
        E.append(cwd, session, row, home=home)
        messages.append(f"{rel} left minified ({why}); .{ext} marked unsafe")
        return

    row["formatter"] = fmt.name
    pre = git_pre_image(cwd, rel)
    ok, err = fmt.format(abspath)
    if not ok:
        row["formatter_ok"] = False
        E.append(cwd, session, row, home=home)
        messages.append(f"{fmt.name} failed on {rel} (likely a syntax error in a collapsed line): {err[:200]}")
        return

    after = Path(abspath).read_text(errors="replace")
    outside = churn_outside(pre, mine, after)
    row.update({"formatter_ok": True, "chars_fmt": chars(after),
                "tok_fmt": estimate(after, k), "churn_outside": outside})
    E.append(cwd, session, row, home=home)
    nlines = max(1, len(after.splitlines()))
    if outside > CHURN_LINES or outside > CHURN_FRACTION * nlines:
        messages.append(f"formatting {rel} caused churn on {outside} lines you did not edit")

def main(stdin_text, home=None):
    try:
        d = json.loads(stdin_text or "")
        cwd = d["cwd"]
        session = d.get("session_id") or "unknown"
        if not isinstance(cwd, str) or not cwd or not isinstance(session, str):
            return 0
    except (ValueError, KeyError, TypeError):
        return 0

    lock = E.harness_dir(cwd, home) / f"{session}.lock"
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except OSError:
        return 0  # a Stop hook already running for this session

    messages = []
    try:
        turn = E.current_turn(cwd, session, home)
        rows = E.read_session(cwd, session, home)
        k, _ = load_k()
        for rel, ops in _files_this_turn(rows, turn).items():
            # Each file is guarded on its own: one file's unexpected failure
            # (a race, a permission error, a disk problem mid-append) must not
            # leave the remaining files of this turn unformatted and unmeasured.
            try:
                _process_file(cwd, session, turn, rel, ops, k, home, messages)
            except Exception as e:
                messages.append(f"error processing {rel}: {type(e).__name__}: {e}")
                continue
        E.bump_turn(cwd, session, home)
    except Exception as e:  # a hook must never break the session
        messages.append(f"internal error: {type(e).__name__}: {e}")
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    _emit(messages)
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.stdin.read()))
