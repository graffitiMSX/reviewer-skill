#!/usr/bin/env python3
# harness/minify/hooks/format_turn.py
"""Stop hook. Formats the files this turn touched and records both token counts."""
import datetime as dt, fcntl, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from harness.minify.lib.classes import classify, ext_of
from harness.minify.lib.estimate import chars, estimate, load_k
from harness.minify.lib.churn import CHURN_LINES, CHURN_FRACTION, churn_outside, git_pre_image
from harness.minify.lib.detect import detect
from harness.minify.lib import events as E, unsafe as U

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

def _is_contained(rel):
    """False for an absolute path or one with a `..` component. FIX 7: format_turn
    is the component that writes to disk (fmt.format runs --write on the joined
    path), so it must not trust a persisted row's `file` field just because
    log_write's own containment guard is sound today -- the log is a file, not a
    value this hook controls."""
    if os.path.isabs(rel):
        return False
    return ".." not in Path(rel).parts

def _process_file(cwd, session, turn, rel, ops, k, home, messages):
    """Measure, format, and re-measure a single file, appending its own row.

    Left to raise on any unexpected failure (a deleted-between-list-and-read race,
    a permission problem, a disk error mid-append) -- the caller guards each file
    individually so one file's exception never stops the files that follow it.
    """
    if not _is_contained(rel):
        return
    if classify(rel) == "exclude":
        return
    abspath = os.path.join(cwd, rel)
    if not os.path.isfile(abspath):
        return
    ext = ext_of(rel)
    mine = Path(abspath).read_text(errors="replace")
    row = {"k": "measure",
           "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "turn": turn, "file": rel, "ext": ext, "class": classify(rel),
           "ops": ops, "style": E.active_style(cwd, home),
           "chars_min": chars(mine), "tok_min": estimate(mine, k),
           "chars_fmt": None, "tok_fmt": None,
           "churn_outside": None, "lines_fmt": None, "pre_image": "unavailable"}

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
    # git_pre_image distinguishes a genuine "no pre-image" answer ("": untracked,
    # unborn HEAD, or not a repo) from a retrieval failure (None: git raised, a NUL
    # byte, undecodable content) -- a transient failure must not silently read as a
    # new file in the log. churn_outside still gets "" either way, matching the
    # existing (parked) conservative behavior for files with no usable pre-image.
    pre = git_pre_image(cwd, rel)
    row["pre_image"] = "git:HEAD" if pre is not None else "unavailable"
    ok, err = fmt.format(abspath)
    if not ok:
        row["formatter_ok"] = False
        E.append(cwd, session, row, home=home)
        messages.append(f"{fmt.name} failed on {rel} (likely a syntax error in a collapsed line): {err[:200]}")
        return

    after = Path(abspath).read_text(errors="replace")
    outside = churn_outside(pre or "", mine, after)
    nlines = max(1, len(after.splitlines()))
    row.update({"formatter_ok": True, "chars_fmt": chars(after),
                "tok_fmt": estimate(after, k), "churn_outside": outside,
                "lines_fmt": nlines})
    E.append(cwd, session, row, home=home)
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

    lock_path = E.harness_dir(cwd, home) / f"{session}.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return 0  # cannot even open/create the lock file; degrade silently

    # FIX 3: fcntl.flock on an open fd, not O_CREAT|O_EXCL existence. The kernel
    # releases an flock when the holding process dies for any reason (SIGKILL, the
    # host's own 60s hook timeout), which removes the stale-lock failure mode
    # entirely rather than mitigating it -- an O_EXCL file left behind by a killed
    # process silently disables the harness for the rest of the session. The lock
    # file itself is kept (never unlinked); only the advisory lock on it is taken
    # and released.
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock_fd)
        _emit(["Stop hook already running for this session (lock held); "
               "this turn was not measured or formatted"])
        return 0

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
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(lock_fd)
    _emit(messages)
    return 0

if __name__ == "__main__":
    try:
        stdin_text = sys.stdin.read()
    except Exception:
        sys.exit(0)
    sys.exit(main(stdin_text))
