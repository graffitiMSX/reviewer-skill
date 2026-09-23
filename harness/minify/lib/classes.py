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
