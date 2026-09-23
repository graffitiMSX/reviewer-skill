# Minify Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a harness that makes Claude Code emit minified code, restores readable formatting with the project's own formatter at every turn end, and reports what the minified emission saved.

**Architecture:** A custom output style carries the emission rules (advisory, no denial hook). A `PostToolUse` hook logs each write; a `Stop` hook formats the files that turn touched and measures each one twice — minified on disk, then formatted — writing both counts to an NDJSON log outside the project. A `SessionStart` hook reports which languages are safe to minify here. A CLI reads the log.

**Tech Stack:** Python 3.13 standard library only. `unittest` for tests (pytest is not installed). Bash for install/uninstall. No runtime network calls, no third-party packages, no installing formatters.

**Spec:** `harness/minify/DESIGN.md`

## Global Constraints

- Python 3.13, **standard library only**. No pip installs, ever.
- Tests use `unittest`. Run with `python3 -m unittest discover -s harness/minify/tests -t .`
- Every hook **always exits 0** and never emits a blocking decision.
- Hooks read only `tool_name`, `tool_input`, `cwd`, `session_id` from stdin JSON. **Never read the tool result** — its key name is not pinned in the docs, and file content comes from disk.
- The harness never installs or downloads a formatter. No formatter for a language means the harness steps aside for that language.
- Log root: `~/.claude/minify-harness/<project-slug>/`. Nothing is written inside the user's project.
- Every module accepts a `home` parameter (default `~`) so tests never touch the real `~/.claude`.
- Half-up rounding everywhere: `_r(x) = int(x + 0.5)`. Never Python's `round()`, whose banker's rounding makes goldens ambiguous.
- Language classes are defined once, in `lib/classes.py`. Nothing else hardcodes an extension list.
- Commit after every task.

## Deliberate deviations from DESIGN.md

Two, both recorded here rather than silently implemented:

1. **`package.json` `scripts.format` is detected but never used to format.** The spec lists it in the detection order, but running `npm run format` formats the whole project, which is exactly the diff-noise Guard 1 exists to prevent. `doctor` reports it as "present, not per-file" and tells the user to add a local prettier. Per-file formatting requires a per-file formatter.
2. **Guard 3 splits by cause.** The spec marks a language unsafe when its formatter is *missing or failed*. A formatter that is present but fails is Guard 2 — almost always a syntax error in a collapsed line — and marking the whole language unsafe for that would disable the harness on a typo. Only a **missing** formatter writes to `unsafe.json`. A failing formatter produces the Guard 2 message and leaves the language armed.

## What the tests can and cannot prove

The harness does not contain a minifier — **the model minifies**. So the round-trip tests in Task 14 are not testing a code path; they validate the **rule table** in `lib/classes.py` and the output style by asserting that a hand-written (readable, minified) fixture pair is semantically identical.

Two of those proofs need no dependencies at all and always run:

- `.py` pairs: `ast.dump(ast.parse(readable)) == ast.dump(ast.parse(dense))`
- `.json` pairs: `json.loads(readable) == json.loads(minified)`

`.ts` and `.css` pairs are proven by formatting both and comparing, which needs prettier, so those tests skip when it is absent. This is why `tsx`/`jsx`/`html` are `dense`-class: no dependency-free parser can prove their whitespace changes are safe.

## File Structure

```
harness/minify/
  DESIGN.md                     approved spec
  PLAN.md                       this plan
  lib/__init__.py
  lib/classes.py                extension -> collapse | dense | exclude; the single source of truth
  lib/estimate.py               token estimator + calibration constant
  lib/events.py                 log paths, append/read, turn counter, active output style
  lib/detect.py                 per-file formatter detection and invocation
  lib/churn.py                  two-diff churn computation
  lib/unsafe.py                 unsafe.json registry
  hooks/log_write.py            PostToolUse
  hooks/format_turn.py          Stop
  hooks/session_doctor.py       SessionStart
  bin/minify-harness            CLI: report, doctor
  bin/minread                   dense-print a file
  output-styles/minified.md     the forcing layer
  install.sh / uninstall.sh
  tests/                        one test module per lib/hook, plus fixtures/
```

Each `lib/` module is independently testable and has one responsibility. The hooks are thin orchestration over them: no hook contains logic that is not tested through a library module.

---

### Task 1: Scaffolding and language classes

**Files:**
- Create: `harness/minify/lib/__init__.py`, `harness/minify/lib/classes.py`
- Create: `harness/minify/tests/__init__.py`, `harness/minify/tests/test_classes.py`

**Interfaces:**
- Consumes: nothing
- Produces: `classify(path: str) -> str` returning `"collapse" | "dense" | "exclude"`; `COLLAPSE: frozenset[str]`, `DENSE: frozenset[str]`, `EXCLUDE_NAMES: frozenset[str]`, `EXCLUDE_GLOBS: tuple[str, ...]` (extensions are stored without the dot)

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_classes.py
import unittest
from harness.minify.lib.classes import classify

class TestClassify(unittest.TestCase):
    def test_collapse_languages(self):
        for p in ["src/api.ts", "a/b.js", "x.mjs", "x.cjs", "s.css", "s.scss", "d.json", "i.svg"]:
            self.assertEqual(classify(p), "collapse", p)

    def test_dense_languages(self):
        for p in ["ui.tsx", "ui.jsx", "page.html", "sync.py", "run.sh", "run.bash", "q.sql"]:
            self.assertEqual(classify(p), "dense", p)

    def test_excluded_extensions(self):
        for p in ["README.md", "doc.mdx", "ci.yaml", "ci.yml", "pyproject.toml"]:
            self.assertEqual(classify(p), "exclude", p)

    def test_excluded_by_name(self):
        for p in ["Dockerfile", "a/Dockerfile", "package-lock.json", "uv.lock", "yarn.lock"]:
            self.assertEqual(classify(p), "exclude", p)

    def test_excluded_by_glob(self):
        for p in ["docker-compose.yml", "docker-compose.prod.yml", ".env", ".env.local",
                  "db/migrations/001_init.sql", "app/migrations/x.py"]:
            self.assertEqual(classify(p), "exclude", p)

    def test_unknown_extension_is_excluded(self):
        self.assertEqual(classify("image.png"), "exclude")
        self.assertEqual(classify("noext"), "exclude")

    def test_lockfile_beats_collapse_extension(self):
        # package-lock.json is .json, which is collapse-class; the name rule must win
        self.assertEqual(classify("package-lock.json"), "exclude")

    def test_migration_beats_dense_extension(self):
        self.assertEqual(classify("app/migrations/0002_add.py"), "exclude")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/alexmarra/projects/rudolf/skills && python3 -m unittest harness.minify.tests.test_classes -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'harness'`

- [ ] **Step 3: Create the package files and implementation**

```bash
mkdir -p harness/minify/lib harness/minify/tests harness/minify/hooks harness/minify/bin harness/minify/output-styles harness/minify/tests/fixtures
touch harness/__init__.py harness/minify/__init__.py harness/minify/lib/__init__.py harness/minify/tests/__init__.py
```

```python
# harness/minify/lib/classes.py
"""Single source of truth for which languages may be minified and how far."""
import fnmatch, os

COLLAPSE = frozenset("ts js mjs cjs css scss json svg".split())
DENSE = frozenset("tsx jsx html py sh bash sql".split())

EXCLUDE_NAMES = frozenset({
    "Dockerfile", "Makefile", "package-lock.json", "yarn.lock",
    "pnpm-lock.yaml", "uv.lock", "poetry.lock", "Cargo.lock", "go.sum",
})
EXCLUDE_GLOBS = ("docker-compose*.yml", "docker-compose*.yaml", ".env", ".env.*", "*.lock")
EXCLUDE_DIRS = ("migrations",)

def classify(path):
    """Return "collapse", "dense" or "exclude" for a file path."""
    name = os.path.basename(path)
    parts = os.path.normpath(path).split(os.sep)
    if name in EXCLUDE_NAMES:
        return "exclude"
    if any(fnmatch.fnmatch(name, g) for g in EXCLUDE_GLOBS):
        return "exclude"
    if any(d in EXCLUDE_DIRS for d in parts[:-1]):
        return "exclude"
    ext = name.rsplit(".", 1)[1].lower() if "." in name else ""
    if ext in COLLAPSE:
        return "collapse"
    if ext in DENSE:
        return "dense"
    return "exclude"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_classes -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add harness/__init__.py harness/minify/__init__.py harness/minify/lib harness/minify/tests
git commit -m "minify: language class table"
```

---

### Task 2: Token estimator

**Files:**
- Create: `harness/minify/lib/estimate.py`, `harness/minify/lib/calibration.json`
- Create: `harness/minify/tests/test_estimate.py`

**Interfaces:**
- Consumes: nothing
- Produces: `estimate(text: str, k: float = 1.0) -> int`, `chars(text: str) -> int`, `load_k(path: str | None = None) -> tuple[float, bool]` returning `(k, calibrated)`

- [ ] **Step 1: Write the failing test**

Goldens are chosen so every run length resolves unambiguously under half-up rounding.

```python
# harness/minify/tests/test_estimate.py
import json, tempfile, unittest
from pathlib import Path
from harness.minify.lib.estimate import estimate, chars, load_k

class TestEstimate(unittest.TestCase):
    def test_word_runs(self):
        self.assertEqual(estimate("ab"), 1)        # 2/4.2 -> 1 (floor of 1)
        self.assertEqual(estimate("abcd"), 1)      # 0.95 -> 1
        self.assertEqual(estimate("abcdefgh"), 2)  # 1.90 -> 2

    def test_digit_run(self):
        self.assertEqual(estimate("12345"), 2)     # 1.67 -> 2

    def test_newline_is_one_token(self):
        self.assertEqual(estimate("\n"), 1)
        self.assertEqual(estimate("\n\n\n"), 3)

    def test_whitespace_run(self):
        self.assertEqual(estimate("    "), 1)      # 0.67 -> 1 via the floor

    def test_punctuation_runs(self):
        self.assertEqual(estimate("=>"), 1)        # 1.25 -> 1
        self.assertEqual(estimate("();=>{}"), 4)   # 4.375 -> 4

    def test_composite_line(self):
        # "const"=1 " "=1 "a"=1 "="=1 "1"=1 ";"=1 "\n"=1
        self.assertEqual(estimate("const a=1;\n"), 7)

    def test_empty(self):
        self.assertEqual(estimate(""), 0)
        self.assertEqual(chars(""), 0)

    def test_chars_counts_utf8_bytes(self):
        self.assertEqual(chars("abc"), 3)
        self.assertEqual(chars("café"), 5)

    def test_k_scales_the_total(self):
        self.assertEqual(estimate("const a=1;\n", k=2.0), 14)

    def test_ratio_is_stable_under_k(self):
        a = "const alpha=1;\n" * 40
        b = "const alpha = 1;\n\n" * 40
        r1 = estimate(a) / estimate(b)
        r2 = estimate(a, k=1.31) / estimate(b, k=1.31)
        self.assertLess(abs(r1 - r2) / r1, 0.02)

    def test_load_k_defaults_to_uncalibrated(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "missing.json"
            self.assertEqual(load_k(str(p)), (1.0, False))

    def test_load_k_reads_calibrated_value(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "calibration.json"
            p.write_text(json.dumps({"k": 1.07, "calibrated": True}))
            self.assertEqual(load_k(str(p)), (1.07, True))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_estimate -v`
Expected: FAIL — `No module named 'harness.minify.lib.estimate'`

- [ ] **Step 3: Write the implementation**

```python
# harness/minify/lib/estimate.py
"""Offline token estimator. Absolute counts are approximate; ratios are stable
because both sides of every comparison use this same function."""
import json, os, re

RUN = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*|\d+|\n|[ \t\r\f\v]+|[^\sA-Za-z0-9_$]+")
DEFAULT_CALIBRATION = os.path.join(os.path.dirname(__file__), "calibration.json")

def _r(x):
    """Half-up rounding. Python's round() is banker's rounding, which makes goldens ambiguous."""
    return int(x + 0.5)

def _run_tokens(run):
    if run == "\n":
        return 1
    c = run[0]
    n = len(run)
    if c.isalpha() or c in "_$":
        return max(1, _r(n / 4.2))
    if c.isdigit():
        return max(1, _r(n / 3))
    if c.isspace():
        return max(1, _r(n / 6))
    return max(1, _r(n / 1.6))

def estimate(text, k=1.0):
    """Estimated token count for a piece of source."""
    if not text:
        return 0
    return _r(k * sum(_run_tokens(m.group(0)) for m in RUN.finditer(text)))

def chars(text):
    """UTF-8 byte length. Needs no estimator and is not arguable."""
    return len(text.encode("utf-8"))

def load_k(path=None):
    """Return (k, calibrated). Missing or malformed calibration means (1.0, False)."""
    path = path or DEFAULT_CALIBRATION
    try:
        with open(path) as fh:
            d = json.load(fh)
        return float(d.get("k", 1.0)), bool(d.get("calibrated", False))
    except (OSError, ValueError):
        return 1.0, False
```

```json
{"k": 1.0, "calibrated": false, "note": "Set k from a one-time count_tokens fit. Ratios are valid uncalibrated."}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_estimate -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add harness/minify/lib/estimate.py harness/minify/lib/calibration.json harness/minify/tests/test_estimate.py
git commit -m "minify: offline token estimator"
```

---

### Task 3: Event log, turn counter, active style

**Files:**
- Create: `harness/minify/lib/events.py`
- Create: `harness/minify/tests/test_events.py`

**Interfaces:**
- Consumes: nothing
- Produces: `project_slug(cwd) -> str`, `harness_dir(cwd, home=None) -> Path`, `log_path(cwd, session_id, home=None) -> Path`, `append(cwd, session_id, obj, home=None) -> None`, `read(path) -> list[dict]`, `read_session(cwd, session_id, home=None) -> list[dict]`, `latest_session(cwd, home=None) -> Path | None`, `all_logs(cwd, home=None) -> list[Path]`, `current_turn(cwd, session_id, home=None) -> int`, `bump_turn(cwd, session_id, home=None) -> int`, `active_style(cwd, home=None) -> str | None`

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_events.py
import json, tempfile, unittest
from pathlib import Path
from harness.minify.lib import events as E

class TestEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.cwd = Path(self.tmp.name) / "proj"
        (self.cwd / ".claude").mkdir(parents=True)
        (self.home / ".claude").mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()

    def test_project_slug_mirrors_claude_code(self):
        self.assertEqual(E.project_slug("/home/a/projects/rudolf/skills"),
                         "-home-a-projects-rudolf-skills")

    def test_append_then_read_roundtrip(self):
        E.append(str(self.cwd), "s1", {"k": "write", "file": "a.ts"}, home=str(self.home))
        E.append(str(self.cwd), "s1", {"k": "write", "file": "b.ts"}, home=str(self.home))
        rows = E.read_session(str(self.cwd), "s1", home=str(self.home))
        self.assertEqual([r["file"] for r in rows], ["a.ts", "b.ts"])

    def test_log_lives_outside_the_project(self):
        E.append(str(self.cwd), "s1", {"k": "write"}, home=str(self.home))
        p = E.log_path(str(self.cwd), "s1", home=str(self.home))
        self.assertTrue(str(p).startswith(str(self.home)))
        self.assertEqual(list(self.cwd.rglob("*.ndjson")), [])

    def test_read_skips_malformed_lines(self):
        p = E.log_path(str(self.cwd), "s1", home=str(self.home))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"k":"write"}\nnot json\n{"k":"measure"}\n')
        self.assertEqual([r["k"] for r in E.read(p)], ["write", "measure"])

    def test_turn_starts_at_one_and_bumps(self):
        self.assertEqual(E.current_turn(str(self.cwd), "s1", home=str(self.home)), 1)
        self.assertEqual(E.bump_turn(str(self.cwd), "s1", home=str(self.home)), 2)
        self.assertEqual(E.current_turn(str(self.cwd), "s1", home=str(self.home)), 2)

    def test_active_style_from_global_settings(self):
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "minified"}))
        self.assertEqual(E.active_style(str(self.cwd), home=str(self.home)), "minified")

    def test_project_local_settings_override_global(self):
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "minified"}))
        (self.cwd / ".claude" / "settings.local.json").write_text(json.dumps({"outputStyle": "default"}))
        self.assertEqual(E.active_style(str(self.cwd), home=str(self.home)), "default")

    def test_active_style_absent_is_none(self):
        self.assertIsNone(E.active_style(str(self.cwd), home=str(self.home)))

    def test_all_logs_and_latest_session(self):
        E.append(str(self.cwd), "s1", {"k": "write"}, home=str(self.home))
        E.append(str(self.cwd), "s2", {"k": "write"}, home=str(self.home))
        self.assertEqual(len(E.all_logs(str(self.cwd), home=str(self.home))), 2)
        self.assertIn(E.latest_session(str(self.cwd), home=str(self.home)).stem, {"s1", "s2"})

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_events -v`
Expected: FAIL — `No module named 'harness.minify.lib.events'`

- [ ] **Step 3: Write the implementation**

```python
# harness/minify/lib/events.py
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
    with open(p, "a") as fh:
        fh.write(json.dumps(obj, separators=(",", ":")) + "\n")

def read(path):
    """Read an NDJSON log, skipping malformed lines rather than failing."""
    rows = []
    try:
        with open(path) as fh:
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
        with open(_state_path(cwd, session_id, home)) as fh:
            return int(json.load(fh).get("turn", 1))
    except (OSError, ValueError):
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
            with open(p) as fh:
                v = json.load(fh).get("outputStyle")
        except (OSError, ValueError):
            continue
        if v:
            style = v
    return style
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_events -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add harness/minify/lib/events.py harness/minify/tests/test_events.py
git commit -m "minify: event log, turn counter, active style"
```

---

### Task 4: PostToolUse write logger

**Files:**
- Create: `harness/minify/hooks/__init__.py`, `harness/minify/hooks/log_write.py`
- Create: `harness/minify/tests/test_log_write.py`

**Interfaces:**
- Consumes: `classes.classify`, `estimate.estimate`, `estimate.chars`, `estimate.load_k`, `events.append`, `events.current_turn`, `events.active_style`
- Produces: `payload_of(tool_name, tool_input) -> str | None`, `main(stdin_text, home=None) -> int` (always returns 0)

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_log_write.py
import json, tempfile, unittest
from pathlib import Path
from harness.minify.hooks.log_write import main, payload_of
from harness.minify.lib import events as E

def hook_input(cwd, tool, tool_input, session="s1"):
    return json.dumps({"session_id": session, "cwd": str(cwd),
                       "hook_event_name": "PostToolUse",
                       "tool_name": tool, "tool_input": tool_input})

class TestPayload(unittest.TestCase):
    def test_write_uses_content(self):
        self.assertEqual(payload_of("Write", {"file_path": "/a.ts", "content": "x=1"}), "x=1")
    def test_edit_uses_new_string(self):
        self.assertEqual(payload_of("Edit", {"file_path": "/a.ts", "old_string": "a", "new_string": "b"}), "b")
    def test_unknown_tool_is_none(self):
        self.assertIsNone(payload_of("Bash", {"command": "ls"}))
    def test_never_reads_tool_result(self):
        self.assertIsNone(payload_of("Write", {"file_path": "/a.ts"}))

class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.cwd = Path(self.tmp.name) / "proj"
        (self.cwd / "src").mkdir(parents=True)
        (self.home / ".claude").mkdir(parents=True)
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "minified"}))
    def tearDown(self):
        self.tmp.cleanup()

    def rows(self, session="s1"):
        return E.read_session(str(self.cwd), session, home=str(self.home))

    def test_logs_a_write_event(self):
        rc = main(hook_input(self.cwd, "Write", {"file_path": "src/api.ts", "content": "const a=1;\n"}),
                  home=str(self.home))
        self.assertEqual(rc, 0)
        r = self.rows()[0]
        self.assertEqual(r["k"], "write")
        self.assertEqual(r["file"], "src/api.ts")
        self.assertEqual(r["ext"], "ts")
        self.assertEqual(r["class"], "collapse")
        self.assertEqual(r["tool"], "Write")
        self.assertEqual(r["turn"], 1)
        self.assertEqual(r["style"], "minified")
        self.assertEqual(r["tok"], 7)
        self.assertEqual(r["chars"], 11)

    def test_absolute_path_is_stored_relative_to_cwd(self):
        main(hook_input(self.cwd, "Write", {"file_path": str(self.cwd / "src/api.ts"), "content": "a"}),
             home=str(self.home))
        self.assertEqual(self.rows()[0]["file"], "src/api.ts")

    def test_excluded_class_is_not_logged(self):
        main(hook_input(self.cwd, "Write", {"file_path": "README.md", "content": "# hi"}), home=str(self.home))
        self.assertEqual(self.rows(), [])

    def test_non_write_tool_is_not_logged(self):
        main(hook_input(self.cwd, "Bash", {"command": "ls"}), home=str(self.home))
        self.assertEqual(self.rows(), [])

    def test_malformed_stdin_exits_zero_and_logs_nothing(self):
        self.assertEqual(main("not json at all", home=str(self.home)), 0)
        self.assertEqual(main("", home=str(self.home)), 0)

    def test_missing_cwd_exits_zero(self):
        self.assertEqual(main(json.dumps({"tool_name": "Write", "tool_input": {}}), home=str(self.home)), 0)

    def test_style_absent_is_recorded_as_none(self):
        (self.home / ".claude" / "settings.json").write_text("{}")
        main(hook_input(self.cwd, "Write", {"file_path": "src/api.ts", "content": "a"}), home=str(self.home))
        self.assertIsNone(self.rows()[0]["style"])

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_log_write -v`
Expected: FAIL — `No module named 'harness.minify.hooks'`

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
# harness/minify/hooks/log_write.py
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_log_write -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Verify the hook survives garbage on a real pipe**

Run: `echo 'garbage' | python3 harness/minify/hooks/log_write.py; echo "exit=$?"`
Expected: `exit=0`, no output, no traceback

- [ ] **Step 6: Commit**

```bash
git add harness/minify/hooks harness/minify/tests/test_log_write.py
git commit -m "minify: PostToolUse write logger"
```

---

### Task 5: Formatter detection

**Files:**
- Create: `harness/minify/lib/detect.py`
- Create: `harness/minify/tests/test_detect.py`

**Interfaces:**
- Consumes: nothing
- Produces: `class Formatter` with attributes `name: str`, `per_file: bool` and methods `format(path) -> tuple[bool, str]`, `check(path) -> tuple[bool, str]`; `detect(root: str, ext: str) -> Formatter | None`

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_detect.py
import json, os, stat, tempfile, unittest
import unittest.mock as mock
from pathlib import Path
from harness.minify.lib.detect import detect

def fake_bin(path, body="#!/bin/sh\nexit 0\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)

class TestDetect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()

    def test_prettier_in_node_modules_wins(self):
        fake_bin(self.root / "node_modules/.bin/prettier")
        fake_bin(self.root / "node_modules/.bin/biome")
        f = detect(str(self.root), "ts")
        self.assertEqual(f.name, "prettier@node_modules")
        self.assertTrue(f.per_file)

    def test_biome_when_prettier_absent(self):
        fake_bin(self.root / "node_modules/.bin/biome")
        self.assertEqual(detect(str(self.root), "css").name, "biome@node_modules")

    def test_ruff_for_python(self):
        fake_bin(self.root / ".venv/bin/ruff")
        self.assertEqual(detect(str(self.root), "py").name, "ruff@venv")

    def test_black_when_ruff_absent(self):
        fake_bin(self.root / ".venv/bin/black")
        self.assertEqual(detect(str(self.root), "py").name, "black@venv")

    def test_npm_script_is_detected_but_not_per_file(self):
        (self.root / "package.json").write_text(json.dumps({"scripts": {"format": "prettier -w ."}}))
        with mock.patch("harness.minify.lib.detect._npx_prettier_ok", return_value=False):
            f = detect(str(self.root), "ts")
        self.assertEqual(f.name, "npm-script:format")
        self.assertFalse(f.per_file)

    def test_nothing_found_is_none(self):
        with mock.patch("harness.minify.lib.detect._npx_prettier_ok", return_value=False):
            self.assertIsNone(detect(str(self.root), "ts"))
        self.assertIsNone(detect(str(self.root), "py"))

    def test_unusable_npx_is_not_offered_as_a_formatter(self):
        with mock.patch("harness.minify.lib.detect._npx_prettier_ok", return_value=False):
            self.assertIsNone(detect(str(self.root), "ts"))
        with mock.patch("harness.minify.lib.detect._npx_prettier_ok", return_value=True):
            self.assertEqual(detect(str(self.root), "ts").name, "npx:prettier")

    def test_unknown_extension_is_none(self):
        fake_bin(self.root / "node_modules/.bin/prettier")
        self.assertIsNone(detect(str(self.root), "png"))

    def test_format_reports_failure_with_stderr(self):
        fake_bin(self.root / ".venv/bin/ruff", "#!/bin/sh\necho 'syntax error' >&2\nexit 2\n")
        ok, err = detect(str(self.root), "py").format(str(self.root / "x.py"))
        self.assertFalse(ok)
        self.assertIn("syntax error", err)

    def test_format_reports_success(self):
        fake_bin(self.root / ".venv/bin/ruff")
        ok, err = detect(str(self.root), "py").format(str(self.root / "x.py"))
        self.assertTrue(ok)
        self.assertEqual(err, "")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_detect -v`
Expected: FAIL — `No module named 'harness.minify.lib.detect'`

- [ ] **Step 3: Write the implementation**

```python
# harness/minify/lib/detect.py
"""Find a per-file formatter a project already has. Never installs anything."""
import json, os, re, shutil, subprocess

NODE_EXTS = frozenset("ts tsx js jsx mjs cjs css scss json html svg".split())
PY_EXTS = frozenset({"py"})
TIMEOUT = 30

class Formatter:
    def __init__(self, name, argv_format, argv_check, per_file=True):
        self.name = name
        self._fmt = argv_format
        self._chk = argv_check
        self.per_file = per_file

    def _run(self, argv, path):
        try:
            p = subprocess.run(argv + [path], capture_output=True, text=True, timeout=TIMEOUT)
            return p.returncode == 0, (p.stderr or p.stdout or "").strip()
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)

    def format(self, path):
        """Rewrite path in place. Returns (ok, stderr)."""
        return self._run(self._fmt, path)

    def check(self, path):
        """True when path is already formatter-clean."""
        return self._run(self._chk, path)

_NPX_OK = None

def _npx_prettier_ok():
    """True only when `npx --no-install prettier` can actually run. A detected but
    unusable formatter would let the harness minify files it cannot un-minify.
    Probed once per process; `npx` exits 0 while printing an error, so the version
    string is what decides."""
    global _NPX_OK
    if _NPX_OK is None:
        npx = shutil.which("npx")
        if not npx:
            _NPX_OK = False
        else:
            try:
                p = subprocess.run([npx, "--no-install", "prettier", "--version"],
                                   capture_output=True, text=True, timeout=TIMEOUT)
                _NPX_OK = p.returncode == 0 and bool(re.match(r"\d+\.\d+", p.stdout.strip()))
            except (OSError, subprocess.SubprocessError):
                _NPX_OK = False
    return _NPX_OK

def _exe(root, rel):
    p = os.path.join(root, rel)
    return p if os.path.isfile(p) and os.access(p, os.X_OK) else None

def _npm_script(root):
    try:
        with open(os.path.join(root, "package.json")) as fh:
            scripts = json.load(fh).get("scripts") or {}
    except (OSError, ValueError):
        return None
    if "format" not in scripts:
        return None
    # Whole-project formatting would rewrite files the session never touched,
    # which is exactly the churn Guard 1 exists to prevent. Detected, not used.
    return Formatter("npm-script:format", ["true"], ["true"], per_file=False)

def detect(root, ext):
    ext = (ext or "").lower()
    if ext in NODE_EXTS:
        p = _exe(root, "node_modules/.bin/prettier")
        if p:
            return Formatter("prettier@node_modules", [p, "--write"], [p, "--check"])
        b = _exe(root, "node_modules/.bin/biome")
        if b:
            return Formatter("biome@node_modules", [b, "format", "--write"], [b, "format"])
        if _npx_prettier_ok():
            npx = shutil.which("npx")
            return Formatter("npx:prettier", [npx, "--no-install", "prettier", "--write"],
                             [npx, "--no-install", "prettier", "--check"])
        return _npm_script(root)
    if ext in PY_EXTS:
        r = _exe(root, ".venv/bin/ruff")
        if r:
            return Formatter("ruff@venv", [r, "format"], [r, "format", "--check"])
        bl = _exe(root, ".venv/bin/black")
        if bl:
            return Formatter("black@venv", [bl, "--quiet"], [bl, "--check", "--quiet"])
        return None
    if ext == "go":
        g = shutil.which("gofmt")
        return Formatter("gofmt", [g, "-w"], [g, "-l"]) if g else None
    if ext == "rs":
        rf = shutil.which("rustfmt")
        return Formatter("rustfmt", [rf], [rf, "--check"]) if rf else None
    return None
```

Ordering note: `npx:prettier` comes before the npm script because it formats one file,
but it is offered **only** when `_npx_prettier_ok()` proves it runs. On this machine it does
not — `npx --no-install prettier` reports a missing package while still exiting 0 — so `ts`
correctly detects as having no formatter, and the harness leaves those files alone instead of
minifying what it cannot restore. Tests patch `_npx_prettier_ok` rather than `shutil.which`,
because the probe memoizes and a `which` patch applied after the first probe has no effect.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_detect -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add harness/minify/lib/detect.py harness/minify/tests/test_detect.py
git commit -m "minify: per-file formatter detection"
```

---

### Task 6: Churn computation

**Files:**
- Create: `harness/minify/lib/churn.py`
- Create: `harness/minify/tests/test_churn.py`

**Interfaces:**
- Consumes: nothing
- Produces: `changed_a(a, b) -> set[int]` (1-based line numbers in `a`), `changed_b(a, b) -> set[int]` (1-based in `b`), `churn_outside(pre, mine, fmt) -> int`, `git_pre_image(root, rel) -> str`

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_churn.py
import subprocess, tempfile, unittest
from pathlib import Path
from harness.minify.lib.churn import changed_a, changed_b, churn_outside, git_pre_image

class TestChurn(unittest.TestCase):
    def test_changed_b_reports_lines_in_b(self):
        self.assertEqual(changed_b("a\nb\nc\n", "a\nB\nc\n"), {2})

    def test_changed_a_reports_lines_in_a(self):
        self.assertEqual(changed_a("a\nb\nc\n", "a\nc\n"), {2})

    def test_insertions_count_in_b_only(self):
        self.assertEqual(changed_b("a\nc\n", "a\nb\nc\n"), {2})
        self.assertEqual(changed_a("a\nc\n", "a\nb\nc\n"), set())

    def test_no_churn_when_formatting_only_touches_my_lines(self):
        pre  = "const a = 1;\nconst b = 2;\n"
        mine = "const a=1;\nconst b = 2;\n"       # I edited line 1
        fmt  = "const a = 1;\nconst b = 2;\n"     # formatter fixed line 1
        self.assertEqual(churn_outside(pre, mine, fmt), 0)

    def test_churn_when_formatting_touches_untouched_lines(self):
        pre  = "const a = 1;\nlet   x=9;\nlet   y=8;\n"
        mine = "const a=1;\nlet   x=9;\nlet   y=8;\n"
        fmt  = "const a = 1;\nlet x = 9;\nlet y = 8;\n"   # lines 2-3 were never mine
        self.assertEqual(churn_outside(pre, mine, fmt), 2)

    def test_new_file_has_no_churn(self):
        self.assertEqual(churn_outside("", "a=1\n", "a = 1\n"), 0)

    def test_git_pre_image_reads_head(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
            Path(d, "a.ts").write_text("const a = 1;\n")
            subprocess.run(["git", "add", "a.ts"], cwd=d, check=True)
            subprocess.run(["git", "commit", "-qm", "x"], cwd=d, check=True)
            Path(d, "a.ts").write_text("const a=1;\n")
            self.assertEqual(git_pre_image(d, "a.ts"), "const a = 1;\n")

    def test_git_pre_image_of_untracked_file_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
            Path(d, "new.ts").write_text("x")
            self.assertEqual(git_pre_image(d, "new.ts"), "")

    def test_git_pre_image_outside_repo_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(git_pre_image(d, "a.ts"), "")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_churn -v`
Expected: FAIL — `No module named 'harness.minify.lib.churn'`

- [ ] **Step 3: Write the implementation**

```python
# harness/minify/lib/churn.py
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
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout if p.returncode == 0 else ""
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_churn -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add harness/minify/lib/churn.py harness/minify/tests/test_churn.py
git commit -m "minify: churn computation from two diffs"
```

---

### Task 7: Unsafe-language registry

**Files:**
- Create: `harness/minify/lib/unsafe.py`
- Create: `harness/minify/tests/test_unsafe.py`

**Interfaces:**
- Consumes: `events.harness_dir`
- Produces: `load(cwd, home=None) -> set[str]`, `mark(cwd, ext, reason, home=None) -> None`, `clear(cwd, ext, home=None) -> bool`, `path(cwd, home=None) -> Path`

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_unsafe.py
import tempfile, unittest
from pathlib import Path
from harness.minify.lib import unsafe as U

class TestUnsafe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self.tmp.name) / "home")
        self.cwd = str(Path(self.tmp.name) / "proj")
    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_by_default(self):
        self.assertEqual(U.load(self.cwd, home=self.home), set())

    def test_mark_then_load(self):
        U.mark(self.cwd, "py", "no formatter found", home=self.home)
        self.assertEqual(U.load(self.cwd, home=self.home), {"py"})

    def test_mark_is_idempotent(self):
        U.mark(self.cwd, "py", "r1", home=self.home)
        U.mark(self.cwd, "py", "r2", home=self.home)
        self.assertEqual(U.load(self.cwd, home=self.home), {"py"})

    def test_clear_removes_and_reports(self):
        U.mark(self.cwd, "py", "r", home=self.home)
        self.assertTrue(U.clear(self.cwd, "py", home=self.home))
        self.assertEqual(U.load(self.cwd, home=self.home), set())

    def test_clear_missing_returns_false(self):
        self.assertFalse(U.clear(self.cwd, "py", home=self.home))

    def test_malformed_file_reads_as_empty(self):
        p = U.path(self.cwd, home=self.home)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{{{ not json")
        self.assertEqual(U.load(self.cwd, home=self.home), set())

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_unsafe -v`
Expected: FAIL — `No module named 'harness.minify.lib.unsafe'`

- [ ] **Step 3: Write the implementation**

```python
# harness/minify/lib/unsafe.py
"""Extensions this project must not minify, because their formatter is missing."""
import datetime as dt, json
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_unsafe -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add harness/minify/lib/unsafe.py harness/minify/tests/test_unsafe.py
git commit -m "minify: unsafe-language registry"
```

---
### Task 8: Stop hook — format the turn and close the metric

**Files:**
- Create: `harness/minify/hooks/format_turn.py`
- Create: `harness/minify/tests/test_format_turn.py`

**Interfaces:**
- Consumes: `classes.classify`, `estimate.estimate/chars/load_k`, `events.*`, `detect.detect`, `churn.churn_outside/git_pre_image`, `unsafe.mark/load`
- Produces: `main(stdin_text, home=None) -> int` (always 0), `CHURN_LINES = 20`, `CHURN_FRACTION = 0.3`

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_format_turn.py
import io, json, os, stat, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from harness.minify.hooks.format_turn import main
from harness.minify.lib import events as E, unsafe as U

def stub(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)

SPACE_EQUALS = "#!/bin/sh\nsed -i 's/=/ = /g' \"$2\"\n"        # argv: --write FILE
REWRITE_ALL  = "#!/bin/sh\nsed -i 's/$/ /' \"$2\"\n"            # touches every line
FAILING      = "#!/bin/sh\necho 'unexpected token' >&2\nexit 2\n"

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self.tmp.name) / "home")
        self.cwd = Path(self.tmp.name) / "proj"
        (self.cwd / "src").mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()

    def hook_in(self, session="s1"):
        return json.dumps({"session_id": session, "cwd": str(self.cwd), "hook_event_name": "Stop"})

    def log_write(self, rel, turn=1, session="s1"):
        E.append(str(self.cwd), session, {"k": "write", "turn": turn, "tool": "Write",
                                          "file": rel, "ext": rel.rsplit(".", 1)[1],
                                          "class": "collapse", "tok": 0, "chars": 0,
                                          "style": "minified"}, home=self.home)

    def run_hook(self, session="s1"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(self.hook_in(session), home=self.home)
        return rc, buf.getvalue()

    def measures(self, session="s1"):
        return [r for r in E.read_session(str(self.cwd), session, home=self.home) if r["k"] == "measure"]

class TestHappyPath(Base):
    def test_measures_minified_then_formatted(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts")
        rc, _ = self.run_hook()
        self.assertEqual(rc, 0)
        m = self.measures()[0]
        self.assertEqual(m["file"], "src/api.ts")
        self.assertEqual(m["tok_min"], 7)     # const a=1;\n
        self.assertEqual(m["tok_fmt"], 9)     # const a = 1;\n
        self.assertTrue(m["formatter_ok"])
        self.assertEqual(m["formatter"], "prettier@node_modules")
        self.assertEqual((self.cwd / "src/api.ts").read_text(), "const a = 1;\n")

    def test_several_writes_to_one_file_make_one_measurement(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts"); self.log_write("src/api.ts"); self.log_write("src/api.ts")
        self.run_hook()
        self.assertEqual(len(self.measures()), 1)
        self.assertEqual(self.measures()[0]["ops"], ["Write", "Write", "Write"])

    def test_turn_is_bumped_and_next_turn_is_isolated(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("a=1\n")
        self.log_write("src/api.ts", turn=1)
        self.run_hook()
        self.assertEqual(E.current_turn(str(self.cwd), "s1", home=self.home), 2)
        self.log_write("src/other.ts", turn=2)
        (self.cwd / "src/other.ts").write_text("b=2\n")
        self.run_hook()
        self.assertEqual([m["file"] for m in self.measures()], ["src/api.ts", "src/other.ts"])

class TestGuards(Base):
    def test_missing_formatter_marks_unsafe_and_warns(self):
        (self.cwd / "src/sync.py").write_text("a=1\n")
        E.append(str(self.cwd), "s1", {"k": "write", "turn": 1, "tool": "Write", "file": "src/sync.py",
                                       "ext": "py", "class": "dense", "tok": 0, "chars": 0,
                                       "style": "minified"}, home=self.home)
        rc, out = self.run_hook()
        self.assertEqual(rc, 0)
        self.assertEqual(U.load(str(self.cwd), home=self.home), {"py"})
        self.assertIn("src/sync.py", out)
        self.assertIn("no formatter", out.lower())
        m = self.measures()[0]
        self.assertFalse(m["formatter_ok"])
        self.assertIsNone(m["tok_fmt"])

    def test_failing_formatter_warns_but_does_not_mark_unsafe(self):
        stub(self.cwd / "node_modules/.bin/prettier", FAILING)
        (self.cwd / "src/api.ts").write_text("const a=1\n")
        self.log_write("src/api.ts")
        rc, out = self.run_hook()
        self.assertEqual(U.load(str(self.cwd), home=self.home), set())
        self.assertIn("unexpected token", out)
        self.assertFalse(self.measures()[0]["formatter_ok"])

    def test_churn_outside_my_edit_is_reported(self):
        import subprocess
        stub(self.cwd / "node_modules/.bin/prettier", REWRITE_ALL)
        subprocess.run(["git", "init", "-q"], cwd=self.cwd, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.cwd, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.cwd, check=True)
        (self.cwd / "src/api.ts").write_text("l1\nl2\nl3\nl4\n")
        subprocess.run(["git", "add", "-A"], cwd=self.cwd, check=True)
        subprocess.run(["git", "commit", "-qm", "x"], cwd=self.cwd, check=True)
        (self.cwd / "src/api.ts").write_text("L1\nl2\nl3\nl4\n")   # only line 1 is mine
        self.log_write("src/api.ts")
        rc, out = self.run_hook()
        self.assertGreaterEqual(self.measures()[0]["churn_outside"], 3)
        self.assertIn("churn", out.lower())

    def test_excluded_file_is_never_formatted(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "README.md").write_text("a=1\n")
        E.append(str(self.cwd), "s1", {"k": "write", "turn": 1, "tool": "Write", "file": "README.md",
                                       "ext": "md", "class": "exclude", "tok": 0, "chars": 0,
                                       "style": "minified"}, home=self.home)
        self.run_hook()
        self.assertEqual(self.measures(), [])
        self.assertEqual((self.cwd / "README.md").read_text(), "a=1\n")

    def test_deleted_file_is_skipped(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        self.log_write("src/gone.ts")
        rc, _ = self.run_hook()
        self.assertEqual(rc, 0)
        self.assertEqual(self.measures(), [])

class TestSafety(Base):
    def test_malformed_stdin_exits_zero(self):
        self.assertEqual(main("nonsense", home=self.home), 0)
        self.assertEqual(main("", home=self.home), 0)

    def test_reentrant_call_is_skipped_by_the_lock(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts")
        lock = E.harness_dir(str(self.cwd), self.home) / "s1.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("held")
        rc, _ = self.run_hook()
        self.assertEqual(rc, 0)
        self.assertEqual(self.measures(), [])

    def test_lock_is_released_after_a_normal_run(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts")
        self.run_hook()
        self.assertFalse((E.harness_dir(str(self.cwd), self.home) / "s1.lock").exists())

    def test_no_output_when_nothing_to_say(self):
        stub(self.cwd / "node_modules/.bin/prettier", SPACE_EQUALS)
        (self.cwd / "src/api.ts").write_text("const a=1;\n")
        self.log_write("src/api.ts")
        _, out = self.run_hook()
        self.assertEqual(out.strip(), "")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_format_turn -v`
Expected: FAIL — `No module named 'harness.minify.hooks.format_turn'`

- [ ] **Step 3: Write the implementation**

```python
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
        seen.setdefault(r["file"], []).append(r.get("tool", "?"))
    return seen

def _emit(messages):
    if not messages:
        return
    text = "minify-harness: " + " | ".join(messages)
    print(json.dumps({
        "systemMessage": text,
        "hookSpecificOutput": {"hookEventName": "Stop", "systemMessage": text},
    }))

def main(stdin_text, home=None):
    try:
        d = json.loads(stdin_text or "")
        cwd = d["cwd"]
        session = d.get("session_id") or "unknown"
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
            if classify(rel) == "exclude":
                continue
            abspath = os.path.join(cwd, rel)
            if not os.path.isfile(abspath):
                continue
            ext = rel.rsplit(".", 1)[1].lower() if "." in rel else ""
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
                continue

            row["formatter"] = fmt.name
            pre = git_pre_image(cwd, rel)
            ok, err = fmt.format(abspath)
            if not ok:
                row["formatter_ok"] = False
                E.append(cwd, session, row, home=home)
                messages.append(f"{fmt.name} failed on {rel} (likely a syntax error in a collapsed line): {err[:200]}")
                continue

            after = Path(abspath).read_text(errors="replace")
            outside = churn_outside(pre, mine, after)
            row.update({"formatter_ok": True, "chars_fmt": chars(after),
                        "tok_fmt": estimate(after, k), "churn_outside": outside})
            E.append(cwd, session, row, home=home)
            nlines = max(1, len(after.splitlines()))
            if outside > CHURN_LINES or outside > CHURN_FRACTION * nlines:
                messages.append(f"formatting {rel} caused churn on {outside} lines you did not edit")
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_format_turn -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add harness/minify/hooks/format_turn.py harness/minify/tests/test_format_turn.py
git commit -m "minify: Stop hook formats the turn and records both token counts"
```

---

### Task 9: Doctor verdict and the SessionStart hook

Adds `lib/doctor.py` to the file structure: the verdict is shared by this hook and the CLI in Task 11, so it lives in a library, not in either caller. Also extends `lib/detect.py` with `check_many`, because a repo-level cleanliness check must be one formatter invocation, not one per file.

**Files:**
- Create: `harness/minify/lib/doctor.py`, `harness/minify/hooks/session_doctor.py`
- Modify: `harness/minify/lib/detect.py` (add `Formatter.check_many`)
- Create: `harness/minify/tests/test_doctor.py`

**Interfaces:**
- Consumes: `classes.COLLAPSE/DENSE`, `detect.detect`, `unsafe.load`
- Produces: `Formatter.check_many(paths: list[str]) -> tuple[bool, str]`; `verdict(cwd, home=None) -> dict` with keys `safe: list[str]`, `blocked: dict[str, str]`, `formatters: dict[str, str | None]`, `repo_clean: bool | None`, `checked: int`; `one_line(v: dict) -> str`; `main(stdin_text, home=None) -> int`
- `repo_clean` is `True`, `False`, or `None` when it could not be determined (no formatter, or not a git repo)

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_doctor.py
import io, json, stat, subprocess, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from harness.minify.lib.doctor import one_line, verdict
from harness.minify.lib import unsafe as U
from harness.minify.hooks.session_doctor import main

CLEAN = "#!/bin/sh\nexit 0\n"
DIRTY = "#!/bin/sh\necho 'a.ts' \nexit 1\n"

def stub(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)

def git_repo(root, files):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    for rel, body in files.items():
        p = Path(root, rel); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)

class TestVerdict(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self.tmp.name) / "home")
        self.cwd = Path(self.tmp.name) / "proj"
        self.cwd.mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()

    def test_ts_is_safe_when_prettier_exists(self):
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        v = verdict(str(self.cwd), home=self.home)
        self.assertIn("ts", v["safe"])
        self.assertEqual(v["formatters"]["ts"], "prettier@node_modules")

    def test_py_is_blocked_without_a_formatter(self):
        v = verdict(str(self.cwd), home=self.home)
        self.assertNotIn("py", v["safe"])
        self.assertIn("py", v["blocked"])

    def test_unsafe_registry_blocks_a_language_with_a_formatter(self):
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        U.mark(str(self.cwd), "ts", "no formatter", home=self.home)
        v = verdict(str(self.cwd), home=self.home)
        self.assertNotIn("ts", v["safe"])
        self.assertIn("marked unsafe", v["blocked"]["ts"])

    def test_repo_clean_true(self):
        git_repo(self.cwd, {"a.ts": "const a = 1;\n"})
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        v = verdict(str(self.cwd), home=self.home)
        self.assertIs(v["repo_clean"], True)
        self.assertGreaterEqual(v["checked"], 1)

    def test_repo_clean_false(self):
        git_repo(self.cwd, {"a.ts": "const a=1;\n"})
        stub(self.cwd / "node_modules/.bin/prettier", DIRTY)
        self.assertIs(verdict(str(self.cwd), home=self.home)["repo_clean"], False)

    def test_repo_clean_unknown_without_git(self):
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        self.assertIsNone(verdict(str(self.cwd), home=self.home)["repo_clean"])

    def test_one_line_mentions_safe_blocked_and_rule(self):
        git_repo(self.cwd, {"a.ts": "const a=1;\n"})
        stub(self.cwd / "node_modules/.bin/prettier", DIRTY)
        line = one_line(verdict(str(self.cwd), home=self.home))
        self.assertIn("safe=", line)
        self.assertIn("py", line)
        self.assertIn("new files only", line)

class TestSessionStartHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self.tmp.name) / "home")
        self.cwd = Path(self.tmp.name) / "proj"
        self.cwd.mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()

    def test_emits_additional_context(self):
        stub(self.cwd / "node_modules/.bin/prettier", CLEAN)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(json.dumps({"cwd": str(self.cwd), "session_id": "s1",
                                  "hook_event_name": "SessionStart", "source": "startup"}),
                      home=self.home)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("safe=", payload["hookSpecificOutput"]["additionalContext"])

    def test_malformed_stdin_exits_zero_silently(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main("garbage", home=self.home), 0)
        self.assertEqual(buf.getvalue().strip(), "")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_doctor -v`
Expected: FAIL — `No module named 'harness.minify.lib.doctor'`

- [ ] **Step 3: Add `check_many` to `lib/detect.py`**

Insert into `class Formatter`, after `check`:

```python
    def check_many(self, paths):
        """One invocation for many paths. Returns (all_clean, output)."""
        if not paths:
            return True, ""
        try:
            p = subprocess.run(self._chk + list(paths), capture_output=True, text=True, timeout=TIMEOUT)
            return p.returncode == 0, (p.stderr or p.stdout or "").strip()
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)
```

- [ ] **Step 4: Write `lib/doctor.py`**

```python
# harness/minify/lib/doctor.py
"""Which languages are safe to minify in this project, and is the repo formatter-clean?"""
import subprocess
from harness.minify.lib.classes import COLLAPSE, DENSE
from harness.minify.lib.detect import detect
from harness.minify.lib.unsafe import load as load_unsafe

MAX_CHECK = 200
CLEAN_PROBE_EXT = "ts"

def _tracked(cwd, exts):
    pats = [f"*.{e}" for e in exts]
    try:
        p = subprocess.run(["git", "ls-files", "-z", "--"] + pats, cwd=cwd,
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return [f for f in p.stdout.split("\0") if f][:MAX_CHECK]

def verdict(cwd, home=None):
    blocked_exts = load_unsafe(cwd, home)
    safe, blocked, formatters = [], {}, {}
    for ext in sorted(COLLAPSE | DENSE):
        f = detect(cwd, ext)
        formatters[ext] = f.name if f else None
        if ext in blocked_exts:
            blocked[ext] = "marked unsafe in unsafe.json"
        elif f is None:
            blocked[ext] = "no formatter"
        elif not f.per_file:
            blocked[ext] = f"{f.name} is not per-file"
        else:
            safe.append(ext)

    repo_clean, checked = None, 0
    probe = detect(cwd, CLEAN_PROBE_EXT)
    if probe is not None and probe.per_file:
        files = _tracked(cwd, sorted(COLLAPSE | DENSE))
        if files:
            checked = len(files)
            ok, _ = probe.check_many(files)
            repo_clean = ok
    return {"safe": safe, "blocked": blocked, "formatters": formatters,
            "repo_clean": repo_clean, "checked": checked}

def one_line(v):
    safe = ",".join(v["safe"]) or "none"
    blocked = ",".join(sorted(v["blocked"])) or "none"
    if v["repo_clean"] is True:
        rule = "repo formatter-clean: minify new and existing files"
    elif v["repo_clean"] is False:
        rule = "repo NOT formatter-clean: minify new files only"
    else:
        rule = "cleanliness unknown: minify new files only"
    return f"minify-harness: safe={safe} | blocked={blocked} | {rule}"
```

- [ ] **Step 5: Write `hooks/session_doctor.py`**

```python
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
    try:
        text = one_line(verdict(cwd, home=home))
    except Exception:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": text}}))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.stdin.read()))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m unittest harness.minify.tests.test_doctor harness.minify.tests.test_detect -v`
Expected: PASS, 9 + 10 tests

- [ ] **Step 7: Commit**

```bash
git add harness/minify/lib/doctor.py harness/minify/lib/detect.py harness/minify/hooks/session_doctor.py harness/minify/tests/test_doctor.py
git commit -m "minify: doctor verdict and SessionStart hook"
```

---

### Task 10: Report

Adds `lib/report.py`: the rendering is worth testing on its own, so the CLI in Task 11 stays a thin argument parser.

**Files:**
- Create: `harness/minify/lib/report.py`
- Create: `harness/minify/tests/test_report.py`

**Interfaces:**
- Consumes: `events.read/all_logs/latest_session`, `estimate.load_k`
- Produces: `measures(paths) -> list[dict]`, `dedupe(rows) -> list[dict]` (last row per `(session, file)`, input order preserved), `by_lang(rows) -> list[dict]`, `render(rows, scope, chars=False, turns=False) -> str`
- `dedupe` and every total ignore rows with `formatter_ok` false or `tok_fmt` null

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_report.py
import json, tempfile, unittest
from pathlib import Path
from harness.minify.lib.report import by_lang, dedupe, measures, render

def row(file, turn, tok_min, tok_fmt, ok=True, session="s1", ext=None):
    return {"k": "measure", "session": session, "turn": turn, "file": file,
            "ext": ext or file.rsplit(".", 1)[1], "tok_min": tok_min, "tok_fmt": tok_fmt,
            "chars_min": tok_min * 3, "chars_fmt": tok_fmt * 3 if tok_fmt else None,
            "formatter_ok": ok, "style": "minified"}

class TestDedupe(unittest.TestCase):
    def test_last_turn_per_file_wins(self):
        rows = [row("a.ts", 1, 100, 150), row("a.ts", 7, 200, 320), row("b.css", 2, 10, 20)]
        self.assertEqual([(r["file"], r["turn"]) for r in dedupe(rows)], [("a.ts", 7), ("b.css", 2)])

    def test_same_file_in_two_sessions_is_two_rows(self):
        rows = [row("a.ts", 1, 100, 150, session="s1"), row("a.ts", 1, 100, 150, session="s2")]
        self.assertEqual(len(dedupe(rows)), 2)

    def test_unformatted_rows_are_dropped(self):
        rows = [row("a.ts", 1, 100, None, ok=False), row("b.ts", 1, 10, 20)]
        self.assertEqual([r["file"] for r in dedupe(rows)], ["b.ts"])

class TestRender(unittest.TestCase):
    def test_totals_and_percentage(self):
        out = render([row("src/api.ts", 1, 412, 631), row("src/card.css", 1, 88, 142)], scope="SESSION s1")
        self.assertIn("src/api.ts", out)
        self.assertIn("500", out)          # tok_min total
        self.assertIn("773", out)          # tok_fmt total
        self.assertIn("273", out)          # saved
        self.assertIn("35%", out)          # 273/773
        self.assertIn("SESSION s1", out)

    def test_empty_report_says_so(self):
        self.assertIn("no measurements", render([], scope="SESSION s1").lower())

    def test_chars_flag_adds_byte_counts(self):
        out = render([row("a.ts", 1, 100, 200)], scope="X", chars=True)
        self.assertIn("chars", out.lower())

    def test_turns_flag_keeps_every_row(self):
        rows = [row("a.ts", 1, 100, 150), row("a.ts", 7, 200, 320)]
        self.assertEqual(render(rows, scope="X", turns=True).count("a.ts"), 2)
        self.assertEqual(render(rows, scope="X").count("a.ts"), 1)

    def test_uncalibrated_estimator_is_labelled(self):
        self.assertIn("uncalibrated", render([row("a.ts", 1, 1, 2)], scope="X").lower())

class TestByLang(unittest.TestCase):
    def test_groups_and_sorts_by_saving(self):
        rows = [row("a.ts", 1, 70, 100), row("b.ts", 1, 70, 100), row("c.css", 1, 50, 100)]
        got = by_lang(dedupe(rows))
        self.assertEqual([g["ext"] for g in got], ["css", "ts"])   # css saves 50%, ts saves 30%
        self.assertEqual(got[1]["tok_min"], 140)

class TestMeasures(unittest.TestCase):
    def test_reads_only_measure_rows_and_tags_the_session(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sess-abc.ndjson"
            p.write_text(json.dumps({"k": "write", "file": "a.ts"}) + "\n"
                         + json.dumps({"k": "measure", "file": "a.ts", "turn": 1,
                                       "tok_min": 1, "tok_fmt": 2, "formatter_ok": True,
                                       "ext": "ts"}) + "\n")
            rows = measures([p])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["session"], "sess-abc")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_report -v`
Expected: FAIL — `No module named 'harness.minify.lib.report'`

- [ ] **Step 3: Write the implementation**

```python
# harness/minify/lib/report.py
"""Read measurement rows and render the savings table."""
from harness.minify.lib.estimate import load_k
from harness.minify.lib.events import read

def measures(paths):
    rows = []
    for p in paths:
        for r in read(p):
            if r.get("k") == "measure":
                r.setdefault("session", getattr(p, "stem", str(p)))
                rows.append(r)
    return rows

def _usable(r):
    return bool(r.get("formatter_ok")) and r.get("tok_fmt") is not None

def dedupe(rows):
    """Last measurement per (session, file), in first-appearance order.
    Rows that were never formatted are ignored."""
    keep, order = {}, []
    for r in rows:
        if not _usable(r):
            continue
        key = (r.get("session"), r["file"])
        if key not in keep:
            order.append(key)
            keep[key] = r
        elif r.get("turn", 0) >= keep[key].get("turn", 0):
            keep[key] = r
    return [keep[k] for k in order]

def _pct(saved, base):
    return f"{round(100 * saved / base)}%" if base else "-"

def by_lang(rows):
    groups = {}
    for r in rows:
        g = groups.setdefault(r["ext"], {"ext": r["ext"], "tok_min": 0, "tok_fmt": 0, "files": 0})
        g["tok_min"] += r["tok_min"]
        g["tok_fmt"] += r["tok_fmt"]
        g["files"] += 1
    for g in groups.values():
        g["saved"] = g["tok_fmt"] - g["tok_min"]
    return sorted(groups.values(), key=lambda g: -(g["saved"] / g["tok_fmt"] if g["tok_fmt"] else 0))

def render(rows, scope, chars=False, turns=False):
    shown = rows if turns else dedupe(rows)
    shown = [r for r in shown if _usable(r)]
    if not shown:
        return f"{scope}\n\n  no measurements yet\n"
    k, calibrated = load_k()
    w = max(len(r["file"]) for r in shown)
    lines = [scope, "", f"  {'file'.ljust(w)}  tok_min  tok_fmt    saved"]
    tmin = tfmt = 0
    for r in sorted(shown, key=lambda r: (r.get("session", ""), r["file"], r.get("turn", 0))):
        saved = r["tok_fmt"] - r["tok_min"]
        tmin += r["tok_min"]
        tfmt += r["tok_fmt"]
        lines.append(f"  {r['file'].ljust(w)}  {r['tok_min']:7}  {r['tok_fmt']:7}  {saved:7} {_pct(saved, r['tok_fmt']):>5}")
    lines.append("  " + "-" * (w + 32))
    saved = tfmt - tmin
    lines.append(f"  {'total'.ljust(w)}  {tmin:7}  {tfmt:7}  {saved:7} {_pct(saved, tfmt):>5}")
    lines.append("")
    lines.append(f"SAVED {_pct(saved, tfmt)} on emitted code")
    if chars:
        cmin = sum(r.get("chars_min") or 0 for r in shown)
        cfmt = sum(r.get("chars_fmt") or 0 for r in shown)
        lines.append(f"chars: {cmin:,} -> {cfmt:,}  ({_pct(cfmt - cmin, cfmt)})")
    lines.append(f"estimator: local regex-class, k={k}, "
                 f"{'calibrated' if calibrated else 'uncalibrated'}, ratio-stable")
    lines.append("counts emitted code only: failed edits and re-reads are not netted out")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_report -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add harness/minify/lib/report.py harness/minify/tests/test_report.py
git commit -m "minify: savings report"
```

---

### Task 11: CLI

**Files:**
- Create: `harness/minify/bin/minify-harness`
- Create: `harness/minify/tests/test_cli.py`

**Interfaces:**
- Consumes: `report.measures/render/by_lang/dedupe`, `doctor.verdict`, `events.latest_session/all_logs`, `unsafe.clear`
- Produces: `main(argv, home=None, cwd=None) -> int` — `0` on success, `1` when `--clear` finds nothing

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_cli.py
import importlib.machinery, importlib.util, io, json, stat, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from harness.minify.lib import events as E, unsafe as U

SPEC = Path("harness/minify/bin/minify-harness").resolve()

def load_cli():
    spec = importlib.util.spec_from_loader("mh_cli", importlib.machinery.SourceFileLoader("mh_cli", str(SPEC)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class TestCLI(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self.tmp.name) / "home")
        self.cwd = str(Path(self.tmp.name) / "proj")
        Path(self.cwd).mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()

    def measure(self, session, file, turn, tok_min, tok_fmt):
        E.append(self.cwd, session, {"k": "measure", "turn": turn, "file": file,
                                     "ext": file.rsplit(".", 1)[1], "tok_min": tok_min,
                                     "tok_fmt": tok_fmt, "chars_min": tok_min * 3,
                                     "chars_fmt": tok_fmt * 3, "formatter_ok": True,
                                     "style": "minified"}, home=self.home)

    def run(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.cli.main(list(argv), home=self.home, cwd=self.cwd)
        return rc, buf.getvalue()

    def test_report_defaults_to_the_latest_session(self):
        self.measure("s1", "a.ts", 1, 10, 20)
        self.measure("s2", "b.ts", 1, 30, 60)
        rc, out = self.run("report")
        self.assertEqual(rc, 0)
        self.assertIn("b.ts", out)
        self.assertNotIn("a.ts", out)

    def test_report_all_spans_sessions(self):
        self.measure("s1", "a.ts", 1, 10, 20)
        self.measure("s2", "b.ts", 1, 30, 60)
        _, out = self.run("report", "--all")
        self.assertIn("a.ts", out)
        self.assertIn("b.ts", out)

    def test_report_by_lang(self):
        self.measure("s1", "a.ts", 1, 70, 100)
        self.measure("s1", "b.css", 1, 50, 100)
        _, out = self.run("report", "--by-lang")
        self.assertIn("css", out)
        self.assertIn("ts", out)

    def test_report_with_no_data(self):
        rc, out = self.run("report")
        self.assertEqual(rc, 0)
        self.assertIn("no measurements", out.lower())

    def test_doctor_prints_safe_and_blocked(self):
        rc, out = self.run("doctor")
        self.assertEqual(rc, 0)
        self.assertIn("minify-safe", out.lower())
        self.assertIn("py", out)

    def test_doctor_clear_removes_an_entry(self):
        U.mark(self.cwd, "py", "no formatter", home=self.home)
        rc, out = self.run("doctor", "--clear", "py")
        self.assertEqual(rc, 0)
        self.assertEqual(U.load(self.cwd, home=self.home), set())
        self.assertIn("cleared", out.lower())

    def test_doctor_clear_missing_returns_one(self):
        rc, out = self.run("doctor", "--clear", "py")
        self.assertEqual(rc, 1)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_cli -v`
Expected: FAIL — the CLI file does not exist

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
# harness/minify/bin/minify-harness
"""Report what minified emission saved, and what is safe to minify here."""
import argparse, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from harness.minify.lib import events as E, unsafe as U
from harness.minify.lib.doctor import verdict
from harness.minify.lib.report import by_lang, dedupe, measures, render

def _report(args, home, cwd):
    if args.all:
        paths, scope = E.all_logs(cwd, home), f"ALL SESSIONS  {os.path.basename(cwd)}"
    else:
        p = E.latest_session(cwd, home)
        paths = [p] if p else []
        scope = f"SESSION {p.stem[:8] if p else '-'}"
    rows = measures(paths)
    if args.by_lang:
        groups = by_lang(dedupe(rows))
        if not groups:
            print(f"{scope}\n\n  no measurements yet")
            return 0
        print(scope, "\n")
        print(f"  {'ext':6} {'files':>5} {'tok_min':>8} {'tok_fmt':>8} {'saved':>7}")
        for g in groups:
            pct = round(100 * g["saved"] / g["tok_fmt"]) if g["tok_fmt"] else 0
            print(f"  {g['ext']:6} {g['files']:5} {g['tok_min']:8} {g['tok_fmt']:8} {g['saved']:6} {pct:3}%")
        return 0
    print(render(rows, scope=scope, chars=args.chars, turns=args.turns), end="")
    return 0

def _doctor(args, home, cwd):
    if args.clear:
        if U.clear(cwd, args.clear, home=home):
            print(f"cleared .{args.clear} from unsafe.json")
            return 0
        print(f".{args.clear} was not marked unsafe")
        return 1
    v = verdict(cwd, home=home)
    print(f"project  {cwd}")
    for ext in sorted(v["formatters"]):
        state = "safe" if ext in v["safe"] else f"NOT safe ({v['blocked'][ext]})"
        print(f"  {ext:6} {str(v['formatters'][ext] or '-'):28} {state}")
    clean = {True: "yes", False: "no", None: "unknown"}[v["repo_clean"]]
    print(f"\nrepo formatter-clean: {clean} ({v['checked']} files checked)")
    print(f"minify-safe: {' '.join(v['safe']) or 'none'}")
    return 0

def main(argv, home=None, cwd=None):
    cwd = cwd or os.getcwd()
    ap = argparse.ArgumentParser(prog="minify-harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("--all", action="store_true")
    r.add_argument("--turns", action="store_true")
    r.add_argument("--by-lang", dest="by_lang", action="store_true")
    r.add_argument("--chars", action="store_true")
    d = sub.add_parser("doctor")
    d.add_argument("--clear", metavar="EXT")
    args = ap.parse_args(argv)
    return _report(args, home, cwd) if args.cmd == "report" else _doctor(args, home, cwd)

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Make it executable and run the tests**

```bash
chmod +x harness/minify/bin/minify-harness
python3 -m unittest harness.minify.tests.test_cli -v
```
Expected: PASS, 7 tests

- [ ] **Step 5: Run it against the real project for a smoke check**

Run: `harness/minify/bin/minify-harness doctor`
Expected: a table listing extensions, `py` marked NOT safe (no formatter on this machine), no traceback

- [ ] **Step 6: Commit**

```bash
git add harness/minify/bin/minify-harness harness/minify/tests/test_cli.py
git commit -m "minify: report and doctor CLI"
```

---

### Task 12: minread

**Files:**
- Create: `harness/minify/lib/dense.py`, `harness/minify/bin/minread`
- Create: `harness/minify/tests/test_dense.py`

**Interfaces:**
- Consumes: `classes.classify`
- Produces: `densify(text, path) -> str`, `main(argv) -> int`

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_dense.py
import unittest
from harness.minify.lib.dense import densify

class TestDensify(unittest.TestCase):
    def test_drops_blank_lines_and_indentation(self):
        self.assertEqual(densify("function f() {\n\n    return 1;\n}\n", "a.ts"),
                         "function f() {\nreturn 1;\n}\n")

    def test_drops_slash_line_comments(self):
        self.assertEqual(densify("// why\nconst a = 1;\n", "a.ts"), "const a = 1;\n")

    def test_drops_block_comments(self):
        self.assertEqual(densify("/* a\n b */\nconst a = 1;\n", "a.ts"), "const a = 1;\n")

    def test_keeps_a_url_inside_a_string(self):
        src = 'const u = "https://x.dev/a";\n'
        self.assertEqual(densify(src, "a.ts"), src)

    def test_drops_hash_comments_in_python(self):
        self.assertEqual(densify("# why\nx = 1\n", "a.py"), "x = 1\n")

    def test_keeps_python_indentation_as_one_space(self):
        self.assertEqual(densify("def f():\n    return 1\n", "a.py"), "def f():\n return 1\n")

    def test_nested_python_indentation_keeps_depth(self):
        got = densify("def f():\n    if x:\n        return 1\n", "a.py")
        self.assertEqual(got, "def f():\n if x:\n  return 1\n")

    def test_excluded_file_is_returned_unchanged(self):
        src = "key:\n  value: 1\n\n"
        self.assertEqual(densify(src, "ci.yml"), src)

    def test_hash_inside_a_python_string_survives(self):
        src = 'x = "# not a comment"\n'
        self.assertEqual(densify(src, "a.py"), src)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_dense -v`
Expected: FAIL — `No module named 'harness.minify.lib.dense'`

- [ ] **Step 3: Write the implementation**

Python indentation is preserved as depth, one space per level, so the dense form still parses. Comment stripping is string-aware, scanning character by character rather than with a regex that cannot tell a comment from a URL.

```python
# harness/minify/lib/dense.py
"""Dense rendering of a file for cheap reading. Comprehension only:
strings taken from this output will not match the real file, so Edit cannot use them."""
from harness.minify.lib.classes import classify

LINE_COMMENT = {"ts": "//", "js": "//", "mjs": "//", "cjs": "//", "tsx": "//", "jsx": "//",
                "css": None, "scss": "//", "json": None, "svg": None, "html": None,
                "py": "#", "sh": "#", "bash": "#", "sql": "--"}
BLOCK = {"ts": ("/*", "*/"), "js": ("/*", "*/"), "mjs": ("/*", "*/"), "cjs": ("/*", "*/"),
         "tsx": ("/*", "*/"), "jsx": ("/*", "*/"), "css": ("/*", "*/"), "scss": ("/*", "*/"),
         "html": ("<!--", "-->"), "svg": ("<!--", "-->")}

def _ext(path):
    return path.rsplit(".", 1)[1].lower() if "." in path else ""

def _strip_comments(text, line_tok, block):
    out, i, n = [], 0, len(text)
    quote = None
    bopen, bclose = block if block else (None, None)
    while i < n:
        c = text[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "\"'`":
            quote = c; out.append(c); i += 1; continue
        if bopen and text.startswith(bopen, i):
            j = text.find(bclose, i + len(bopen))
            i = n if j < 0 else j + len(bclose)
            continue
        if line_tok and text.startswith(line_tok, i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        out.append(c); i += 1
    return "".join(out)

def _py_depth(line, unit):
    lead = len(line) - len(line.lstrip(" "))
    return lead // unit if unit else 0

def densify(text, path):
    """Dense form of `text`. Excluded files come back unchanged."""
    if classify(path) == "exclude":
        return text
    ext = _ext(path)
    text = _strip_comments(text, LINE_COMMENT.get(ext), BLOCK.get(ext))
    lines = [l.rstrip() for l in text.splitlines()]
    lines = [l for l in lines if l.strip()]
    if ext in ("py",):
        leads = [len(l) - len(l.lstrip(" ")) for l in lines if l.startswith(" ")]
        unit = min(leads) if leads else 4
        out = [(" " * _py_depth(l, unit)) + l.strip() for l in lines]
    else:
        out = [l.strip() for l in lines]
    return "\n".join(out) + ("\n" if out else "")
```

```python
#!/usr/bin/env python3
# harness/minify/bin/minread
"""Print a dense form of a file. For orientation, not for sourcing Edit strings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from harness.minify.lib.dense import densify

def main(argv):
    if len(argv) != 1:
        print("usage: minread <file>", file=sys.stderr)
        return 2
    p = Path(argv[0])
    try:
        text = p.read_text(errors="replace")
    except OSError as e:
        print(f"minread: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(densify(text, str(p)))
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
chmod +x harness/minify/bin/minread
python3 -m unittest harness.minify.tests.test_dense -v
```
Expected: PASS, 9 tests

- [ ] **Step 5: Smoke-check it against a real file**

Run: `harness/minify/bin/minread harness/minify/lib/classes.py | head -20`
Expected: the module with its docstring and comments gone and one-space indentation, still valid-looking Python

- [ ] **Step 6: Commit**

```bash
git add harness/minify/lib/dense.py harness/minify/bin/minread harness/minify/tests/test_dense.py
git commit -m "minify: minread dense reader"
```

---

### Task 13: The output style

**Files:**
- Create: `harness/minify/output-styles/minified.md`
- Create: `harness/minify/tests/test_style.py`

**Interfaces:**
- Consumes: `classes.COLLAPSE/DENSE`
- Produces: the installed output style; a test that the style's extension lists and `lib/classes.py` can never drift apart

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_style.py
import re, unittest
from pathlib import Path
from harness.minify.lib.classes import COLLAPSE, DENSE

STYLE = Path("harness/minify/output-styles/minified.md")

def listed(label):
    text = STYLE.read_text()
    m = re.search(rf"^<!-- {label}: (.+) -->$", text, re.M)
    return frozenset(m.group(1).split()) if m else frozenset()

class TestStyle(unittest.TestCase):
    def test_file_exists_with_frontmatter(self):
        text = STYLE.read_text()
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: minified", text)
        self.assertIn("description:", text)

    def test_collapse_list_matches_classes_module(self):
        self.assertEqual(listed("collapse"), COLLAPSE)

    def test_dense_list_matches_classes_module(self):
        self.assertEqual(listed("dense"), DENSE)

    def test_states_the_asi_rule(self):
        self.assertIn("semicolon insertion", STYLE.read_text())

    def test_states_the_minread_constraint(self):
        self.assertIn("minread", STYLE.read_text())

    def test_tells_the_model_to_respect_the_session_verdict(self):
        self.assertIn("minify-harness:", STYLE.read_text())

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_style -v`
Expected: FAIL — the style file does not exist

- [ ] **Step 3: Write the output style**

The machine-readable comments are what the drift test reads.

```markdown
---
name: minified
description: Emit code minified so it costs fewer output tokens; the harness formats it back at turn end.
---

# Minified emission

Emit code as densely as the language allows. The harness runs the project's own
formatter on every file you touch at the end of the turn, so the human never reads
what you emit — they read the formatted result. Spending output tokens on
indentation and blank lines buys nothing.

## Collapse class

<!-- collapse: ts js mjs cjs css scss json svg -->

Collapse to one line wherever it stays legal. Use `;` separators, no blank lines, no
indentation. Never join lines that rely on automatic semicolon insertion — add the
explicit `;` instead, or leave the break in.

```
export async function sync(id,o={}){const r=await fetch(`/api/${id}`,{method:"POST"});if(!r.ok)throw new Error(`fail ${r.status}`);const d=await r.json();return{id,items:d.items??[],at:Date.now()}}
.card{display:flex;gap:8px;padding:12px;border-radius:6px}
```

## Dense class

<!-- dense: tsx jsx html py sh bash sql -->

Do not collapse these. Whitespace is significant: Python's indentation carries the
block structure, and in `tsx`, `jsx` and `html` the whitespace between inline
elements is rendered. Emit one statement per line, one space of indent per level, no
blank lines.

```
def sync(id,o=None):
 r=post(f"/api/{id}")
 if not r.ok:raise RuntimeError(r.status)
 return{"id":id,"items":r.json().get("items",[])}
```

## Never minify

Markdown, YAML, TOML, Dockerfiles, compose files, `.env*`, lock files and anything
under a `migrations/` directory. Emit those exactly as you normally would.

## Comments

Keep them. Compress them. The shortest form that keeps the necessary information:
`// retry: 429 only`, not the deletion of the reason and not a full sentence. Drop
banner separators, restated type signatures and anything a reader can see from the
code itself.

## Respect the session verdict

At session start the harness injects a line beginning `minify-harness:`. It names the
extensions that are safe here and whether the repo is formatter-clean. Obey it:

- An extension it does not list as safe has no formatter available. Emit it normally —
  minifying it would leave it minified permanently.
- `repo NOT formatter-clean` means minify new files only. Edits to existing files are
  emitted normally, because formatting those files would rewrite lines nobody touched.

## Prose

Say what changed and why it is correct, once, briefly. No preamble, no restating the
code in English, no summary of a summary.

## Reading files

`minread <file>` prints a file with comments, blank lines and indentation stripped,
which costs fewer input tokens than reading it whole. Use it to survey code you are
not about to edit. Do not source `Edit` strings from it — they will not match the
real file, and the re-read costs more than the saving.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_style -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add harness/minify/output-styles/minified.md harness/minify/tests/test_style.py
git commit -m "minify: output style with drift test against the class table"
```

---

### Task 14: Round-trip equivalence fixtures

These validate the **rule table**, not a code path — the model does the minifying. A fixture pair that is not semantically identical means a rule in the output style is wrong.

**Files:**
- Create: `harness/minify/tests/fixtures/pairs/{sync.readable.py,sync.min.py,config.readable.json,config.min.json,api.readable.ts,api.min.ts,card.readable.css,card.min.css,asi.readable.js,asi.collapsed.js}`
- Create: `harness/minify/tests/test_roundtrip.py`

**Interfaces:**
- Consumes: `detect.detect`
- Produces: nothing importable; proof that the rules hold

- [ ] **Step 1: Write the fixtures**

```python
# harness/minify/tests/fixtures/pairs/sync.readable.py
def sync(record_id, opts=None):
    opts = opts or {}
    response = post(f"/api/{record_id}", timeout=opts.get("timeout", 5))
    if not response.ok:
        raise RuntimeError(response.status)
    return {"id": record_id, "items": response.json().get("items", [])}
```

```python
# harness/minify/tests/fixtures/pairs/sync.min.py
def sync(record_id,opts=None):
 opts=opts or {}
 response=post(f"/api/{record_id}",timeout=opts.get("timeout",5))
 if not response.ok:raise RuntimeError(response.status)
 return{"id":record_id,"items":response.json().get("items",[])}
```

`config.readable.json`:

```json
{
  "name": "demo",
  "retries": 3,
  "hosts": ["a.dev", "b.dev"],
  "nested": { "on": true, "off": false, "nil": null }
}
```

`config.min.json`:

```json
{"name":"demo","retries":3,"hosts":["a.dev","b.dev"],"nested":{"on":true,"off":false,"nil":null}}
```

`api.readable.ts`:

```typescript
export async function sync(id: string, opts: Opts = {}): Promise<Result> {
  const res = await fetch(`/api/${id}`, { method: "POST" });

  if (!res.ok) {
    throw new Error(`fail ${res.status}`);
  }

  const data = await res.json();
  return { id, items: data.items ?? [], at: Date.now() };
}
```

`api.min.ts`:

```typescript
export async function sync(id:string,opts:Opts={}):Promise<Result>{const res=await fetch(`/api/${id}`,{method:"POST"});if(!res.ok)throw new Error(`fail ${res.status}`);const data=await res.json();return{id,items:data.items??[],at:Date.now()}}
```

`card.readable.css`:

```css
.card {
  display: flex;
  gap: 8px;

  padding: 12px;
  border-radius: 6px;
}
```

`card.min.css`:

```css
.card{display:flex;gap:8px;padding:12px;border-radius:6px}
```

The ASI pair is the negative control: `asi.readable.js` relies on automatic semicolon
insertion, and `asi.collapsed.js` is what naive collapsing produces. The test asserts
they are **not** equivalent — proof that the style's ASI rule is load-bearing.

`asi.readable.js`:

```javascript
function pick(a, b) {
  const x = a
  const y = b
  return x + y
}
```

`asi.collapsed.js`:

```javascript
function pick(a,b){const x=a const y=b return x+y}
```

- [ ] **Step 2: Write the failing test**

```python
# harness/minify/tests/test_roundtrip.py
import ast, json, subprocess, tempfile, unittest
from pathlib import Path
from harness.minify.lib.detect import detect

F = Path("harness/minify/tests/fixtures/pairs")

def prettier():
    """The repo's own prettier, or None. TS/CSS proofs need a real formatter."""
    return detect(str(Path.cwd()), "ts")

def fmt_with(tool, text, suffix):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"f{suffix}"
        p.write_text(text)
        ok, err = tool.format(str(p))
        return (p.read_text() if ok else None), err

class TestNoDependencyProofs(unittest.TestCase):
    """These always run: ast and json prove equivalence with no formatter at all."""

    def test_python_pair_is_semantically_identical(self):
        a = ast.dump(ast.parse((F / "sync.readable.py").read_text()))
        b = ast.dump(ast.parse((F / "sync.min.py").read_text()))
        self.assertEqual(a, b)

    def test_dense_python_still_parses(self):
        ast.parse((F / "sync.min.py").read_text())

    def test_json_pair_is_identical(self):
        a = json.loads((F / "config.readable.json").read_text())
        b = json.loads((F / "config.min.json").read_text())
        self.assertEqual(a, b)

    def test_asi_collapse_is_not_valid_javascript_shape(self):
        # No JS parser in the stdlib, so assert the hazard textually: the collapsed
        # form joined two statements with no separator between them.
        collapsed = (F / "asi.collapsed.js").read_text()
        self.assertIn("const x=a const y=b", collapsed)
        self.assertNotIn(";", collapsed.split("{", 1)[1].split("}")[0])

class TestFormatterProofs(unittest.TestCase):
    """Skipped when the project has no prettier: TS and CSS need a real parser."""

    def setUp(self):
        self.tool = prettier()
        if self.tool is None or not self.tool.per_file:
            self.skipTest("no per-file prettier available in this project")

    def test_ts_pair_formats_to_the_same_thing(self):
        a, _ = fmt_with(self.tool, (F / "api.readable.ts").read_text(), ".ts")
        b, _ = fmt_with(self.tool, (F / "api.min.ts").read_text(), ".ts")
        self.assertIsNotNone(a); self.assertIsNotNone(b)
        self.assertEqual(a, b)

    def test_css_pair_formats_to_the_same_thing(self):
        a, _ = fmt_with(self.tool, (F / "card.readable.css").read_text(), ".css")
        b, _ = fmt_with(self.tool, (F / "card.min.css").read_text(), ".css")
        self.assertEqual(a, b)

    def test_asi_collapsed_js_fails_to_format(self):
        out, err = fmt_with(self.tool, (F / "asi.collapsed.js").read_text(), ".js")
        self.assertIsNone(out, "naive ASI collapsing must not format cleanly")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the test**

Run: `python3 -m unittest harness.minify.tests.test_roundtrip -v`
Expected: 4 PASS, 3 SKIPPED (`no per-file prettier available in this project`) — this machine has no prettier, which is exactly the condition `doctor` reports

- [ ] **Step 4: Prove the skipped half really works**

Run it once inside a project that has prettier installed locally:

```bash
cd /tmp && mkdir -p pretest && cd pretest && npm i -D prettier --silent
cd /home/alexmarra/projects/rudolf/skills
cp -r harness /tmp/pretest/ && cd /tmp/pretest && python3 -m unittest harness.minify.tests.test_roundtrip -v
```
Expected: 7 PASS, 0 SKIPPED. If `test_ts_pair_formats_to_the_same_thing` fails, the minified fixture is not equivalent and the **style rule is wrong** — fix the rule, not the test. Clean up `/tmp/pretest` afterwards.

- [ ] **Step 5: Commit**

```bash
git add harness/minify/tests/fixtures harness/minify/tests/test_roundtrip.py
git commit -m "minify: round-trip equivalence fixtures"
```

---

### Task 15: Install and uninstall

**Files:**
- Create: `harness/minify/lib/settings.py`, `harness/minify/install.sh`, `harness/minify/uninstall.sh`
- Create: `harness/minify/tests/test_settings.py`
- Create: `harness/minify/README.md`

**Interfaces:**
- Consumes: nothing
- Produces: `patch(settings_path, root) -> list[str]` (events changed), `unpatch(settings_path) -> list[str]`, `MARKER = "minify/hooks/"`

- [ ] **Step 1: Write the failing test**

```python
# harness/minify/tests/test_settings.py
import json, tempfile, unittest
from pathlib import Path
from harness.minify.lib.settings import MARKER, patch, unpatch

EXISTING = {
    "permissions": {"defaultMode": "auto"},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]}],
        "SessionStart": [{"matcher": "*", "hooks": [
            {"type": "command", "command": "bash '/home/x/.claude/hooks/herdr-agent-state.sh' session",
             "timeout": 10}]}],
    },
}

class TestPatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "settings.json"
        self.p.write_text(json.dumps(EXISTING, indent=2))
        self.root = "/opt/harness/minify"
    def tearDown(self):
        self.tmp.cleanup()

    def load(self):
        return json.loads(self.p.read_text())

    def commands(self, event):
        return [h["command"] for g in self.load()["hooks"].get(event, []) for h in g["hooks"]]

    def test_adds_all_three_hooks(self):
        patch(str(self.p), self.root)
        self.assertTrue(any("log_write.py" in c for c in self.commands("PostToolUse")))
        self.assertTrue(any("format_turn.py" in c for c in self.commands("Stop")))
        self.assertTrue(any("session_doctor.py" in c for c in self.commands("SessionStart")))

    def test_preserves_the_rtk_hook(self):
        patch(str(self.p), self.root)
        self.assertIn("rtk hook claude", self.commands("PreToolUse"))

    def test_preserves_the_existing_session_start_hook(self):
        patch(str(self.p), self.root)
        cmds = self.commands("SessionStart")
        self.assertTrue(any("herdr-agent-state.sh" in c for c in cmds))
        self.assertEqual(len(cmds), 2)

    def test_joins_the_existing_star_matcher_group(self):
        patch(str(self.p), self.root)
        groups = [g for g in self.load()["hooks"]["SessionStart"] if g["matcher"] == "*"]
        self.assertEqual(len(groups), 1)

    def test_post_tool_use_matcher_is_write_or_edit(self):
        patch(str(self.p), self.root)
        self.assertEqual(self.load()["hooks"]["PostToolUse"][0]["matcher"], "Write|Edit")

    def test_patch_is_idempotent(self):
        patch(str(self.p), self.root)
        patch(str(self.p), self.root)
        self.assertEqual(len([c for c in self.commands("SessionStart") if MARKER in c]), 1)
        self.assertEqual(len(self.commands("Stop")), 1)

    def test_unpatch_restores_the_original_exactly(self):
        patch(str(self.p), self.root)
        unpatch(str(self.p))
        self.assertEqual(self.load(), EXISTING)

    def test_unpatch_on_a_clean_file_changes_nothing(self):
        unpatch(str(self.p))
        self.assertEqual(self.load(), EXISTING)

    def test_patch_creates_a_backup(self):
        patch(str(self.p), self.root)
        self.assertTrue(Path(str(self.p) + ".minify-bak").exists())

    def test_patch_on_a_settings_file_with_no_hooks_key(self):
        self.p.write_text(json.dumps({"theme": "dark"}))
        patch(str(self.p), self.root)
        self.assertEqual(self.load()["theme"], "dark")
        self.assertTrue(any("format_turn.py" in c for c in self.commands("Stop")))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest harness.minify.tests.test_settings -v`
Expected: FAIL — `No module named 'harness.minify.lib.settings'`

- [ ] **Step 3: Write `lib/settings.py`**

```python
# harness/minify/lib/settings.py
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest harness.minify.tests.test_settings -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Write the install and uninstall scripts**

```bash
#!/usr/bin/env bash
# harness/minify/install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

mkdir -p "$CLAUDE_HOME/output-styles" "$BIN_DIR"
ln -sf "$ROOT/output-styles/minified.md" "$CLAUDE_HOME/output-styles/minified.md"
ln -sf "$ROOT/bin/minify-harness" "$BIN_DIR/minify-harness"
ln -sf "$ROOT/bin/minread" "$BIN_DIR/minread"
python3 -c "
import sys; sys.path.insert(0, '$ROOT/../..')
from harness.minify.lib.settings import patch
print('patched:', patch('$CLAUDE_HOME/settings.json', '$ROOT') or 'nothing (already installed)')
"
echo "installed. activate with:  /output-style minified"
echo "check what is safe here:   minify-harness doctor"
```

```bash
#!/usr/bin/env bash
# harness/minify/uninstall.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

rm -f "$CLAUDE_HOME/output-styles/minified.md" "$BIN_DIR/minify-harness" "$BIN_DIR/minread"
python3 -c "
import sys; sys.path.insert(0, '$ROOT/../..')
from harness.minify.lib.settings import unpatch
print('unpatched:', unpatch('$CLAUDE_HOME/settings.json') or 'nothing')
"
echo "removed. logs kept at ~/.claude/minify-harness/ — delete them by hand if you want them gone."
```

- [ ] **Step 6: Test install and uninstall against a throwaway CLAUDE_HOME**

```bash
chmod +x harness/minify/install.sh harness/minify/uninstall.sh
export TESTHOME=$(mktemp -d)
cp ~/.claude/settings.json "$TESTHOME/settings.json"
CLAUDE_HOME="$TESTHOME" BIN_DIR="$TESTHOME/bin" harness/minify/install.sh
python3 -c "
import json;d=json.load(open('$TESTHOME/settings.json'))
print('rtk intact:', any('rtk' in h['command'] for g in d['hooks']['PreToolUse'] for h in g['hooks']))
print('SessionStart hooks:', [h['command'][-30:] for g in d['hooks']['SessionStart'] for h in g['hooks']])
print('Stop hooks:', len(d['hooks']['Stop'][0]['hooks']))
"
CLAUDE_HOME="$TESTHOME" BIN_DIR="$TESTHOME/bin" harness/minify/install.sh   # idempotency
CLAUDE_HOME="$TESTHOME" BIN_DIR="$TESTHOME/bin" harness/minify/uninstall.sh
diff <(python3 -m json.tool ~/.claude/settings.json) <(python3 -m json.tool "$TESTHOME/settings.json") && echo "RESTORED IDENTICAL"
rm -rf "$TESTHOME"
```
Expected: `rtk intact: True`, two SessionStart hooks, one Stop hook after two installs, and `RESTORED IDENTICAL` at the end.

**Do not run `install.sh` against the real `~/.claude` in this step.** Installation touches the user's live harness and is their call, not the plan's.

- [ ] **Step 7: Write the README**

```markdown
# minify harness

Emit code minified, format it back with the project's own formatter at turn end,
and measure what the minified emission saved.

    ./install.sh                  # symlinks + three hook entries in ~/.claude/settings.json
    /output-style minified        # arm it
    minify-harness doctor         # what is safe to minify in this project
    minify-harness report         # what it saved this session
    ./uninstall.sh                # reverse everything

Design: `DESIGN.md`. Plan: `PLAN.md`.

The report counts emitted code only. A failed `Edit` against a formatted file costs a
re-read that the number does not net out, so treat it as "savings on emitted code",
not "savings on the session".

Tests: `python3 -m unittest discover -s harness/minify/tests -t .` from the repo root.
Three round-trip tests skip unless the project has a local prettier.
```

- [ ] **Step 8: Run the whole suite**

Run: `python3 -m unittest discover -s harness/minify/tests -t . -v`
Expected: all tests pass, 3 skipped (the prettier-dependent round-trip proofs)

- [ ] **Step 9: Commit**

```bash
git add harness/minify/lib/settings.py harness/minify/install.sh harness/minify/uninstall.sh harness/minify/tests/test_settings.py harness/minify/README.md
git commit -m "minify: install, uninstall, README"
```

---

## Done means

- `python3 -m unittest discover -s harness/minify/tests -t .` passes from the repo root, with only the prettier-dependent round-trip tests skipped.
- `minify-harness doctor` runs in this repo and reports `py` as NOT safe, because no formatter is installed on this machine.
- `install.sh` and `uninstall.sh` round-trip a copy of the real `settings.json` to byte-identical JSON, with the `rtk` hook untouched.
- Nothing has been installed into the live `~/.claude` — that step is the user's.
