"""Find a per-file formatter a project already has. Never installs anything."""
import json, os, re, shutil, subprocess

# Each node formatter gets its OWN capability set rather than one shared NODE_EXTS.
# prettier has no parser for svg; biome does not format scss, html or svg either --
# sharing one set let detect() claim a formatter for an extension it cannot actually
# handle (FIX 1). check_many callers must intersect against these, not COLLAPSE|DENSE.
PRETTIER_EXTS = frozenset("ts tsx js jsx mjs cjs css scss json html".split())
BIOME_EXTS = frozenset("ts tsx js jsx mjs cjs json css".split())
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
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            return False, str(e)

    def format(self, path):
        """Rewrite path in place. Returns (ok, stderr)."""
        return self._run(self._fmt, path)

    def check(self, path):
        """True when path is already formatter-clean."""
        return self._run(self._chk, path)

    def check_many(self, paths):
        """One invocation for many paths. Returns (all_clean, output)."""
        if not paths:
            return True, ""
        try:
            p = subprocess.run(self._chk + list(paths), capture_output=True, text=True, timeout=TIMEOUT)
            return p.returncode == 0, (p.stderr or p.stdout or "").strip()
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            return False, str(e)

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
    if ext in PRETTIER_EXTS:
        p = _exe(root, "node_modules/.bin/prettier")
        if p:
            return Formatter("prettier@node_modules", [p, "--write"], [p, "--check"])
    if ext in BIOME_EXTS:
        b = _exe(root, "node_modules/.bin/biome")
        if b:
            return Formatter("biome@node_modules", [b, "format", "--write"], [b, "format"])
    if ext in PRETTIER_EXTS:
        # Fallbacks below both run prettier itself (npx) or trust the project's own
        # script, so they are only offered for extensions prettier itself claims.
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
    return None
