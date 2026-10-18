#!/usr/bin/env python3
"""Build and query a code map: the repository as a graph the reviewers can ask.

Usage:
  codemap.py build <repo> [-o <out dir>] [--engine auto|cgr|builtin]
  codemap.py status <repo> [<map dir>]
  codemap.py ensure <repo> [-o <out dir>] [--engine auto|cgr|builtin]   (rebuild only if stale)
  codemap.py <query> <map dir> <argument> [--depth N]

Queries:
  deps <path>       what this file imports           rdeps <path>     what imports it
  impact <path>     everything that depends on it, and the routes that reach it
  route <text>      routes matching the text, with middleware, handler and tables
  table <name>      where a table is defined, read and written
  symbol <name>     where a function, method or class is defined
  callers <name>    who calls it (cgr engine only)   callees <name>   what it calls

The default out dir is <repo>/docs/remediation/code-map. `build` writes
graph.json plus one short markdown view per concern: code-map.md (index),
modules.md, entry-points.md, data.md and frontend.md.

Two engines produce the same graph.json:
  cgr      code-graph-rag's offline index: tree-sitter symbols and call edges
           for every language it supports. Used when `cgr` is installed.
  builtin  no dependencies. Imports, routes, jobs and table use for
           TypeScript, JavaScript and Python, at file level, without calls.

Everything here is extracted by pattern, so the map is a set of leads with
file and line, not proof. `status` compares a hash of every source file with
the one taken at build time and exits 1 when the map is missing or any source
file was added, removed or changed, committed or not; pipeline documents and
other non-source files do not count. `ensure` runs `build` only in that case.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict, deque
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
JS_EXT = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
CODE_EXT = JS_EXT + (".py",)
SCAN_EXT = CODE_EXT + (".sql", ".prisma")
SKIP_DIRS = {"node_modules", "dist", "build", ".git", "vendor", "coverage", ".next", "__pycache__", ".venv", "venv",
             "storybook-static", "out", "target", ".turbo", ".cache"}
TEST = re.compile(r"(^|/)(__tests__|tests?|e2e|__mocks__|fixtures|cypress|playwright)/|\.(test|spec|stories|e2e)\.[a-z]+$|(^|/)(test_[^/]+|conftest)\.py$")
MIGRATION = re.compile(r"(^|/)(migrations?|seeds?|alembic)/|\.sql$|\.prisma$")
HTTP_CLIENT = re.compile(r"^(axios|api|http|https|client|request|fetch|apiClient|httpClient|instance|agent|supertest|got|ky|\$http)$", re.I)
ROUTE_CALL = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\.\s*(get|post|put|patch|delete|all|use)\s*\(")
IMPORT_FROM = re.compile(r"""\b(?:import|export)\s+(?:type\s+)?([^'";]*?)\s*\bfrom\s*['"]([^'"]+)['"]""")
IMPORT_BARE = re.compile(r"""(?:^|;)\s*import\s+['"]([^'"]+)['"]|\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)""", re.M)
REQUIRE = re.compile(r"""(?:(?:const|let|var)\s+(\w+|\{[^}]*\})\s*=\s*)?\brequire\(\s*['"]([^'"]+)['"]\s*\)""")
PY_IMPORT = re.compile(r"^[ \t]*(?:from\s+([.\w]+)\s+import\s+([^\n#]+)|import\s+([\w., ]+))", re.M)
SQL_REF = re.compile(r"\b(DELETE\s+FROM|INSERT\s+INTO|UPDATE|FROM|JOIN)\s+(?:ONLY\s+)?\"?([a-z_][a-z0-9_]*)\"?")
SQL_STOP = {"select", "set", "the", "a", "an", "to", "it", "this", "that", "lateral", "unnest", "generate_series", "jsonb_array_elements"}
SCHEMA = [
    re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\w+\.)?\"?(\w+)\"?", re.I),
    re.compile(r"\bcreateTable\(\s*['\"](\w+)['\"]"),
    re.compile(r"@Entity\(\s*(?:\{\s*name:\s*)?['\"](\w+)['\"]"),
    re.compile(r"__tablename__\s*=\s*['\"](\w+)['\"]"),
    re.compile(r"\b(?:pgTable|mysqlTable|sqliteTable)\(\s*['\"](\w+)['\"]"),
    re.compile(r"\.define\(\s*['\"](\w+)['\"]"),
    re.compile(r"^model\s+(\w+)\s*\{", re.M),
    re.compile(r"@@map\(\s*\"(\w+)\"\s*\)"),
]
BUILDER = re.compile(r"\.(?:from|table|into)\(\s*['\"](\w+)['\"]|\bknex\(\s*['\"](\w+)['\"]")
PRISMA = re.compile(r"\bprisma\.(\w+)\.(find\w*|count|aggregate|groupBy|create\w*|update\w*|upsert|delete\w*)\b")
JOBS = [
    ("schedule", re.compile(r"\bcron\.schedule\(|new CronJob\(|@Cron\(|scheduleJob\(|\bsetInterval\(|@periodic_task|schedule\.every\(")),
    ("consumer", re.compile(r"new Worker\(|@Processor\(|\bchannel\.consume\(|@shared_task|@\w+\.task\b|\bLISTEN\s+\w+|FOR UPDATE SKIP LOCKED")),
    ("producer", re.compile(r"new Queue\(|sendToQueue\(|\.publish\(|\.delay\(|apply_async\(|pg_notify\(")),
]
JOB_DIR = re.compile(r"(^|/)(jobs?|workers?|cron|consumers?|queues?|tasks|schedulers?)/[^/]+$")
CLIENT_ROUTE = re.compile(r"""path\s*[=:]\s*\{?\s*['"]([^'"]+)['"]\s*\}?[^<>]{0,160}?(?:element\s*[=:]\s*\{?\s*<\s*(\w+)|[cC]omponent\s*[=:]\s*\{?\s*(\w+))""", re.S)
API_CALL = re.compile(r"""\b([A-Za-z_$][\w$]*)\.(get|post|put|patch|delete)\s*(?:<[^>()]*>)?\(\s*([`'"])(/[^`'"]*)\3""")
FETCH = re.compile(r"""\bfetch\(\s*([`'"])([^`'"]+)\1(?:\s*,\s*\{[^}]{0,200}?method:\s*['"](\w+)['"])?""", re.S)
PY_ROUTE = re.compile(r"^[ \t]*@(\w+)\.(get|post|put|patch|delete|route|websocket)\(\s*['\"]([^'\"]*)['\"][^\n]*\n(?:[ \t]*@[^\n]*\n)*[ \t]*(?:async\s+)?def\s+(\w+)", re.M)
NEST = re.compile(r"@(Get|Post|Put|Patch|Delete|All)\(\s*['\"]?([^'\")]*)['\"]?\s*\)(?:\s*@[^\n]*)*\s*(?:public\s+|private\s+|async\s+)*(\w+)\s*\(")


# ---------- files ----------

def run(cmd, cwd=None, timeout=60):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def list_files(repo):
    listed = run(["git", "ls-files", "-co", "--exclude-standard"], cwd=repo)
    if listed is not None:
        names = listed.splitlines()
    else:
        names = []
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            names += [os.path.relpath(os.path.join(root, f), repo) for f in files]
    keep = []
    for name in names:
        name = name.replace(os.sep, "/")
        if name.endswith(SCAN_EXT) and not name.endswith((".min.js", ".d.ts")) and not SKIP_DIRS.intersection(name.split("/")):
            keep.append(name)
    return sorted(keep)


class Sources:
    def __init__(self, repo):
        self.repo, self.cache = Path(repo), {}

    def text(self, path):
        if path not in self.cache:
            full = self.repo / path
            try:
                self.cache[path] = full.read_text(encoding="utf-8", errors="replace") if full.stat().st_size < 1_500_000 else ""
            except OSError:
                self.cache[path] = ""
        return self.cache[path]


def fingerprint(repo, files):
    """Short content hash per source file, so freshness ignores commits and docs."""
    out = {}
    for path in files:
        try:
            out[path] = hashlib.sha1((Path(repo) / path).read_bytes()).hexdigest()[:12]
        except OSError:
            pass
    return out


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def commented(text, pos):
    start = text.rfind("\n", 0, pos) + 1
    return text[start:pos].lstrip().startswith(("//", "*", "/*", "#"))


# ---------- imports ----------

def resolve_js(importer, spec, fileset):
    if spec.startswith("."):
        base = os.path.normpath(os.path.join(os.path.dirname(importer), spec)).replace(os.sep, "/")
    elif spec.startswith(("@/", "~/")):
        parts = importer.split("/")
        if "src" not in parts:
            return None
        root = "/".join(parts[: len(parts) - parts[::-1].index("src")])
        base = f"{root}/{spec[2:]}"
    else:
        return None
    stems = [base] + ([base.rsplit(".", 1)[0]] if base.endswith((".js", ".jsx", ".mjs", ".cjs")) else [])
    for stem in stems:
        if stem in fileset:
            return stem
        for ext in JS_EXT:
            for cand in (stem + ext, f"{stem}/index{ext}"):
                if cand in fileset:
                    return cand
    return None


def package_name(spec):
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") and len(parts) > 1 else parts[0]


def bindings_of(clause):
    """import clause -> {local name: imported name}; '*' for a namespace, 'default' for a default import."""
    names = {}
    clause = clause.strip()
    braces = re.search(r"\{([^}]*)\}", clause)
    if braces:
        for part in braces.group(1).split(","):
            part = part.strip().removeprefix("type ").strip()
            if part:
                imported, _, local = part.partition(" as ")
                names[(local or imported).strip()] = imported.strip()
        clause = clause[: braces.start()] + clause[braces.end():]
    for part in clause.split(","):
        part = part.strip()
        if part.startswith("* as "):
            names[part[5:].strip()] = "*"
        elif re.fullmatch(r"[\w$]+", part):
            names[part] = "default"
    return names


def js_imports(path, text, fileset):
    """-> (internal targets, external packages, {local name: (module path, imported name)})."""
    internal, external, bound = set(), set(), {}

    def add(spec, clause=None):
        target = resolve_js(path, spec, fileset)
        if target:
            internal.add(target)
            for local, imported in (bindings_of(clause) if clause else {}).items():
                bound[local] = (target, imported)
        elif not spec.startswith((".", "@/", "~/", "node:")):
            external.add(package_name(spec))

    for m in IMPORT_FROM.finditer(text):
        add(m.group(2), m.group(1))
    for m in IMPORT_BARE.finditer(text):
        add(m.group(1) or m.group(2))
    for m in REQUIRE.finditer(text):
        add(m.group(2), m.group(1))
    return internal, external, bound


def py_imports(path, text, fileset):
    internal, external = set(), set()

    def resolve(module, level):
        parts = [p for p in module.split(".") if p]
        here = path.split("/")[:-1]
        roots = [here[: len(here) - level + 1]] if level else [here[:i] for i in range(len(here), -1, -1)]
        for root in roots:
            stem = "/".join(root + parts)
            for cand in (f"{stem}.py", f"{stem}/__init__.py"):
                if cand in fileset:
                    return cand
        return None

    for m in PY_IMPORT.finditer(text):
        if m.group(1):
            module = m.group(1)
            level = len(module) - len(module.lstrip("."))
            target = resolve(module.lstrip("."), level)
            for name in ([] if target and not target.endswith("__init__.py") else re.findall(r"\w+", m.group(2))):
                sub = resolve(f"{module.lstrip('.')}.{name}".lstrip("."), level)
                if sub:
                    internal.add(sub)
            if target:
                internal.add(target)
            elif not level:
                external.add(module.split(".")[0])
        else:
            for module in re.findall(r"[\w.]+", m.group(3).split(" as ")[0]):
                target = resolve(module, 0)
                (internal if target else external).add(target or module.split(".")[0])
    return internal, external


# ---------- cgr engine ----------

def cgr_python():
    exe = shutil.which("cgr")
    if not exe:
        return None, "cgr is not installed"
    try:
        shebang = open(exe, "rb").readline().decode(errors="replace").strip()
    except OSError:
        return None, "cannot read the cgr launcher"
    python = shebang[2:].split()[0] if shebang.startswith("#!") else ""
    if not python or not os.path.exists(python) or "python" not in os.path.basename(python):
        return None, "cannot find the Python interpreter cgr runs under"
    return python, None


def cgr_graph(repo):
    """-> (decoded index, None) or (None, reason it could not be used)."""
    python, why = cgr_python()
    if not python:
        return None, why
    with tempfile.TemporaryDirectory(prefix="codemap-") as tmp:
        # cgr is run on a copy of the working tree, never on the repository itself:
        # it keeps a .cgr-* cache next to the code it indexes, and a repeat run
        # against that cache returns only what changed, while also marking the
        # files as synced for the owner's own cgr database. It also reads a .env
        # from its working directory and rejects keys it does not know.
        copy = Path(tmp) / Path(repo).name
        listed = run(["git", "ls-files", "-co", "--exclude-standard"], cwd=repo)
        names = listed.splitlines() if listed is not None else [
            os.path.relpath(os.path.join(root, f), repo) for root, dirs, files in os.walk(repo)
            if not dirs.__setitem__(slice(None), [d for d in dirs if d not in SKIP_DIRS]) for f in files]
        for name in names:
            source = Path(repo) / name
            if SKIP_DIRS.intersection(name.split("/")) or name.startswith(".cgr-") or not source.is_file() or source.stat().st_size > 1_500_000:
                continue
            (copy / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, copy / name)
        out = Path(tmp) / "index"
        out.mkdir()
        done = subprocess.run(["cgr", "-q", "index", "--repo-path", str(copy), "-o", str(out)], cwd=out,
                              capture_output=True, text=True, timeout=3600)
        index = out / "index.bin"
        if done.returncode != 0 or not index.exists() or index.stat().st_size < 1000:
            last = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["it wrote an empty index"]
            return None, "cgr index failed: " + last[0][:200]
        decoded = subprocess.run([python, str(HERE / "cgr_decode.py"), str(index)], capture_output=True, text=True, timeout=600)
        if decoded.returncode != 0:
            return None, "cannot decode the cgr index: " + decoded.stderr.strip().splitlines()[-1][:200]
        return json.loads(decoded.stdout), None


# ---------- scans ----------

def balanced(text, start, limit=200_000):
    """text of a call's arguments, from just after its opening parenthesis."""
    depth, i, quote = 1, start, None
    end = min(len(text), start + limit)
    while i < end:
        c = text[i]
        if not quote and c == "/" and text[i + 1: i + 2] in ("/", "*"):
            close = text.find("\n", i) if text[i + 1] == "/" else text.find("*/", i + 2)
            i = end if close < 0 else close + 1
            continue
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    return None


def split_args(text):
    args, depth, quote, cur = [], 0, None, []
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            cur.append(c)
            if c == "\\" and i + 1 < len(text):
                cur.append(text[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
            cur.append(c)
        elif c == "/" and text[i:i + 2] == "//":
            nl = text.find("\n", i)
            i = len(text) if nl < 0 else nl
            continue
        elif c in "([{":
            depth += 1
            cur.append(c)
        elif c in ")]}":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    last = "".join(cur).strip()
    return args + ([last] if last else [])


def literal(arg):
    m = re.fullmatch(r"(['\"`])([^'\"`$]*)\1", arg.strip())
    return m.group(2) if m else None


def short(arg):
    arg = " ".join(arg.split())
    if re.fullmatch(r"[\w$.]+", arg):
        return arg
    call = re.match(r"([\w$.]+)\(", arg)
    if call:
        inner = arg[call.end():-1] if arg.endswith(")") else ""
        return f"{call.group(1)}({inner})" if len(inner) <= 40 else f"{call.group(1)}(…)"
    return "inline"


def handler_of(arg):
    """unwrap wrappers such as catchAsync(controller.method) down to the name that handles the request."""
    arg = arg.strip()
    for _ in range(4):
        call = re.fullmatch(r"([\w$.]+)\((.*)\)", arg, re.S)
        if not call:
            break
        inner = split_args(call.group(2))
        if not inner or not re.match(r"[\w$.]+(\(|$)", inner[-1].strip()):
            break
        arg = inner[-1].strip()
    return arg if re.fullmatch(r"[\w$.]+", arg) else None


def scan_js_routes(path, text, bound):
    routes, uses = [], []
    for m in ROUTE_CALL.finditer(text):
        if commented(text, m.start()):
            continue
        inside = balanced(text, m.end())
        args, recv, verb = split_args(inside if inside is not None else text[m.end(): m.end() + 1500]), m.group(1), m.group(2)
        # an inline handler ends the argument list for our purposes; when the call could
        # not be balanced, whatever follows the handler's opening is not an argument
        inline_at = next((i for i, a in enumerate(args) if re.match(r"(async\b|function\b|\([^)]*\)\s*(:[^=]+)?=>|\w+\s*=>)", a)), None)
        if inline_at is not None:
            args = args[: inline_at] + ["inline"]
        elif inside is None:
            continue
        if not args:
            continue
        entry = {"recv": recv, "pos": m.start(), "line": line_of(text, m.start()), "args": args}
        if verb == "use":
            uses.append(entry)
            continue
        path_arg = literal(args[0])
        if path_arg is None or len(args) < 2 or HTTP_CLIENT.match(recv) or not (path_arg == "" or path_arg[0] in "/*:"):
            continue
        name = handler_of(args[-1])
        target = bound.get(name.split(".")[0]) if name else None
        symbol = name.split(".")[-1] if name else None
        if target and "." not in name and target[1] not in ("*", "default"):
            symbol = target[1]
        entry.update(method=verb.upper(), path=path_arg, handler=name or "inline",
                     handler_file=target[0] if target else path, symbol=symbol, inline=[short(a) for a in args[1:-1]])
        routes.append(entry)
    return routes, uses


def join_path(*parts):
    out = "/" + "/".join(p.strip("/") for p in parts if p and p.strip("/"))
    return out


def collect_routes(files, src, bindings):
    per_file, uses_by_file = {}, {}
    for path in files:
        if not path.endswith(JS_EXT) or TEST.search(path):
            continue
        text = src.text(path)
        if ".use(" not in text and not re.search(r"\.(get|post|put|patch|delete|all)\(", text):
            continue
        routes, uses = scan_js_routes(path, text, bindings.get(path, {}))
        if routes:
            per_file[path] = routes
        if uses:
            uses_by_file[path] = uses

    def imported(path, arg):
        name = re.match(r"[\w$]+", arg.strip())
        target = bindings.get(path, {}).get(name.group(0)) if name else None
        return target[0] if target and target[0] != path else None

    # a router is a file that declares routes, or one that only mounts other routers
    routers, grew = set(per_file), True
    while grew:
        grew = False
        for path, uses in uses_by_file.items():
            if path not in routers and any(imported(path, u["args"][-1]) in routers for u in uses):
                routers.add(path)
                grew = True

    def mount_target(path, arg):
        target = imported(path, arg)
        return target if target in routers else None

    mounts, stack_of = defaultdict(list), defaultdict(list)
    for path, uses in uses_by_file.items():
        for use in uses:
            target = mount_target(path, use["args"][-1])
            prefix = literal(use["args"][0])
            if target:
                middle = use["args"][1:-1] if prefix is not None else use["args"][:-1]
                mounts[target].append((path, prefix or "", [short(a) for a in middle], use["line"]))
            elif prefix is None:
                stack_of[(path, use["recv"])].append((use["pos"], use["line"], [short(a) for a in use["args"]]))

    def prefixes(path, seen=()):
        if path not in mounts or path in seen:
            return [("", [], None)]
        out = []
        for parent, prefix, middle, line in mounts[path]:
            for up_prefix, up_mw, _ in prefixes(parent, seen + (path,)):
                out.append((join_path(up_prefix, prefix), up_mw + middle, f"{parent}:{line}"))
        return out

    result = []
    for path, routes in sorted(per_file.items()):
        for route in routes:
            local = [mw for pos, _, names in stack_of.get((path, route["recv"]), []) if pos < route["pos"] for mw in names]
            for prefix, mount_mw, mounted_at in prefixes(path):
                result.append({"method": route["method"], "path": join_path(prefix, route["path"]), "file": path,
                               "line": route["line"], "middleware": mount_mw + local + route["inline"],
                               "handler": route["handler"], "handler_file": route["handler_file"],
                               "symbol": route["symbol"], "mounted_at": mounted_at})
    app_stack = []
    for (path, recv), entries in stack_of.items():
        if path not in mounts and any(p == path for ms in mounts.values() for p, *_ in ms):
            app_stack += [{"file": path, "line": line, "middleware": names} for _, line, names in entries]
    return result, sorted(app_stack, key=lambda e: (e["file"], e["line"]))


def collect_other_routes(files, src):
    routes = []
    for path in files:
        if TEST.search(path):
            continue
        text = src.text(path)
        if path.endswith(".py") and "@" in text:
            prefix = re.search(r"(?:APIRouter|Blueprint)\([^)]*?(?:url_)?prefix\s*=\s*['\"]([^'\"]*)['\"]", text, re.S)
            for m in PY_ROUTE.finditer(text):
                method = "ANY" if m.group(2) == "route" else m.group(2).upper()
                routes.append({"method": method, "path": join_path(prefix.group(1) if prefix else "", m.group(3)),
                               "file": path, "line": line_of(text, m.start()), "middleware": [], "handler": m.group(4),
                               "handler_file": path, "symbol": m.group(4), "mounted_at": None})
        elif path.endswith(JS_EXT) and "@Controller(" in text:
            base = re.search(r"@Controller\(\s*['\"]?([^'\")]*)", text)
            guards = re.findall(r"@UseGuards\(([^)]*)\)", text)
            for m in NEST.finditer(text):
                routes.append({"method": m.group(1).upper(), "path": join_path(base.group(1) if base else "", m.group(2)),
                               "file": path, "line": line_of(text, m.start()), "middleware": sorted(set(guards)),
                               "handler": m.group(3), "handler_file": path, "symbol": m.group(3), "mounted_at": None})
    return routes


def collect_jobs(files, src):
    jobs = []
    for path in files:
        if not path.endswith(CODE_EXT) or TEST.search(path) or path.endswith((".tsx", ".jsx")):
            continue
        text = src.text(path)
        if JOB_DIR.search(path):
            jobs.append({"kind": "job file", "file": path, "line": 1, "text": next((l.strip() for l in text.splitlines() if l.strip()), "")[:110]})
        for kind, pattern in JOBS:
            for m in pattern.finditer(text):
                if commented(text, m.start()):
                    continue
                start = text.rfind("\n", 0, m.start()) + 1
                end = text.find("\n", m.start())
                jobs.append({"kind": kind, "file": path, "line": line_of(text, m.start()),
                             "text": " ".join(text[start: end if end > 0 else len(text)].split())[:110]})
    return jobs


def collect_tables(files, src):
    known = {}
    for path in files:
        if not (MIGRATION.search(path) or "models" in path or "entities" in path or "schema" in path):
            continue
        text = src.text(path)
        for pattern in SCHEMA:
            for m in pattern.finditer(text):
                known.setdefault(m.group(1).lower(), []).append([path, line_of(text, m.start())])
    tables = {name: {"schema": refs[:6], "read": [], "write": []} for name, refs in known.items()}
    for path in files:
        if not path.endswith(CODE_EXT) or TEST.search(path) or MIGRATION.search(path):
            continue
        text = src.text(path)
        hits = []
        for m in SQL_REF.finditer(text):
            verb = m.group(1).split()[0]
            hits.append((m.group(2), "read" if verb in ("FROM", "JOIN") else "write", m.start()))
        for m in BUILDER.finditer(text):
            tail = text[m.end(): m.end() + 240]
            hits.append((m.group(1) or m.group(2), "write" if re.search(r"\.(insert|update|delete|del|upsert)\(", tail) else "read", m.start()))
        for m in PRISMA.finditer(text):
            hits.append((m.group(1), "read" if m.group(2).startswith(("find", "count", "aggregate", "groupBy")) else "write", m.start()))
        for name, mode, pos in hits:
            name = name.lower()
            if known and name not in known:
                plural = next((k for k in (name + "s", name + "es", name.rstrip("y") + "ies") if k in known), None)
                if not plural:
                    continue
                name = plural
            elif not known and name in SQL_STOP:
                continue
            tables.setdefault(name, {"schema": [], "read": [], "write": []})[mode].append([path, line_of(text, pos)])
    return tables


def collect_frontend(files, src, route_files):
    pages, calls = [], []
    for path in files:
        if not path.endswith(JS_EXT) or TEST.search(path) or path in route_files:
            continue
        text = src.text(path)
        if "path" in text and ("<Route" in text or "createBrowserRouter" in text or "RouteObject" in text):
            for m in CLIENT_ROUTE.finditer(text):
                pages.append({"path": m.group(1), "component": m.group(2) or m.group(3), "file": path, "line": line_of(text, m.start())})
        for m in API_CALL.finditer(text):
            if not commented(text, m.start()) and not re.search(r"(router|app|server|routes?)$", m.group(1), re.I):
                calls.append({"method": m.group(2).upper(), "path": m.group(4), "file": path, "line": line_of(text, m.start())})
        for m in FETCH.finditer(text):
            if m.group(2).startswith(("/", "http", "$")):
                calls.append({"method": (m.group(3) or "GET").upper(), "path": m.group(2), "file": path, "line": line_of(text, m.start())})
    return pages, calls


def norm_path(path):
    path = re.sub(r"^https?://[^/]+", "", path.split("?")[0])
    path = re.sub(r"^\$\{[^}]+\}", "", path)
    path = re.sub(r":\w+\??|\$\{[^}]+\}|\{[^}]+\}|\[[^\]]+\]", "{}", path)
    return "/" + path.strip("/")


def same_endpoint(client, server):
    if client == server:
        return True
    for longer, shorter in ((server, client), (client, server)):
        if shorter != "/" and longer.endswith(shorter) and longer[: -len(shorter)].count("/") <= 2:
            return True
    return False


# ---------- build ----------

def build_graph(repo, engine):
    repo = Path(repo).resolve()
    files = list_files(repo)
    if not files:
        sys.exit(f"error: no source files found under {repo}")
    fileset, src = set(files), Sources(repo)
    code = [f for f in files if f.endswith(CODE_EXT)]
    imports, externals, bindings = defaultdict(set), defaultdict(set), {}
    for path in code:
        text = src.text(path)
        if path.endswith(".py"):
            internal, external = py_imports(path, text, fileset)
        else:
            internal, external, bindings[path] = js_imports(path, text, fileset)
        imports[path] |= internal - {path}
        for pkg in external:
            externals[pkg].add(path)

    symbols, calls, note, used = [], [], None, "builtin"
    if engine in ("auto", "cgr"):
        decoded, why = cgr_graph(repo)
        if decoded:
            used = "cgr"
            modules = {n["qn"]: n["path"] for n in decoded["nodes"] if n["kind"] == "module" and n["path"]}
            owner_cache = {}

            def owner(qn):
                if qn not in owner_cache:
                    parts = qn.split(".")
                    owner_cache[qn] = next((".".join(parts[:i]) for i in range(len(parts), 0, -1) if ".".join(parts[:i]) in modules), None)
                return owner_cache[qn]

            index_of = {}
            for node in decoded["nodes"]:
                if node["kind"] == "module":
                    continue
                mod = owner(node["qn"])
                if mod:
                    index_of[node["qn"]] = len(symbols)
                    symbols.append([modules[mod], node["kind"], node["qn"][len(mod) + 1:], node["start"], node["end"]])
            for kind, source, target, target_label in decoded["rels"]:
                if kind == "IMPORTS" and source in modules:
                    if target in modules:
                        if modules[target] != modules[source]:
                            imports[modules[source]].add(modules[target])
                    elif target_label == "ExternalModule" and not target.startswith("builtin."):
                        if not modules[source].endswith(CODE_EXT):
                            externals[target.split(".")[0]].add(modules[source])
                elif kind == "CALLS" and source in index_of and target in index_of:
                    a, b = index_of[source], index_of[target]
                    # a call from product code into a test file is a name collision, not a call
                    if a != b and not (TEST.search(symbols[b][0]) and not TEST.search(symbols[a][0])):
                        calls.append([a, b])
            # cgr resolves calls by name, so two functions that share a name get linked.
            # A real call needs the caller's file to import the callee's, directly or
            # through one re-exporting index file; the rest are dropped.
            def can_see(src_file, dst_file):
                near = imports.get(src_file, ())
                return src_file == dst_file or dst_file in near or any(dst_file in imports.get(mid, ()) for mid in near)
            calls = [[a, b] for a, b in calls if can_see(symbols[a][0], symbols[b][0])]
        elif engine == "cgr":
            sys.exit(f"error: {why}")
        else:
            note = f"cgr was not used ({why}); built with the builtin engine, so there are no symbols or call edges"

    js_routes, app_stack = collect_routes(files, src, bindings)
    routes = js_routes + collect_other_routes(files, src)
    pages, api_calls = collect_frontend(files, src, {r["file"] for r in routes})
    module_list = sorted(set(code) | set(imports) | {t for ts in imports.values() for t in ts} | {s[0] for s in symbols})
    index = {m: i for i, m in enumerate(module_list)}
    head = (run(["git", "rev-parse", "HEAD"], cwd=repo) or "").strip()
    dirty = bool((run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=repo) or "").strip())
    return {
        "meta": {"repo": repo.name, "engine": used, "note": note, "commit": head, "dirty": dirty, "built": date.today().isoformat(),
                 "sources": fingerprint(repo, files)},
        "modules": module_list,
        "imports": sorted([index[a], index[b]] for a, targets in imports.items() for b in targets),
        "externals": {pkg: sorted(index[m] for m in mods) for pkg, mods in sorted(externals.items())},
        "symbols": [[index[s[0]]] + s[1:] for s in symbols],
        "calls": calls,
        "routes": sorted(routes, key=lambda r: (r["path"], r["method"])),
        "app_middleware": app_stack,
        "jobs": collect_jobs(files, src),
        "tables": collect_tables(files, src),
        "pages": pages,
        "api_calls": api_calls,
    }


# ---------- graph helpers ----------

class Map:
    def __init__(self, graph):
        self.g = graph
        self.modules = graph["modules"]
        self.out, self.inc = defaultdict(set), defaultdict(set)
        for a, b in graph["imports"]:
            self.out[a].add(b)
            self.inc[b].add(a)
        self.symbols = graph["symbols"]
        self.calls_out, self.calls_in = defaultdict(set), defaultdict(set)
        for a, b in graph["calls"]:
            self.calls_out[a].add(b)
            self.calls_in[b].add(a)
        self.by_module = defaultdict(list)
        for i, (mod, _, _, start, end) in enumerate(self.symbols):
            self.by_module[mod].append((start, end, i))
        self.index = {m: i for i, m in enumerate(self.modules)}

    def is_test(self, i):
        return bool(TEST.search(self.modules[i]))

    def find_module(self, text):
        exact = self.index.get(text.lstrip("./"))
        if exact is not None:
            return [exact]
        return [i for i, m in enumerate(self.modules) if m.endswith(text) or text in m][:12]

    def closure(self, start, edges, depth):
        seen, queue = {s: 0 for s in start}, deque(start)
        while queue:
            node = queue.popleft()
            if seen[node] >= depth:
                continue
            for nxt in edges[node]:
                if nxt not in seen:
                    seen[nxt] = seen[node] + 1
                    queue.append(nxt)
        return seen

    def enclosing(self, module, line):
        best = None
        for start, end, i in self.by_module.get(module, ()):
            if start <= line <= end and (best is None or end - start < best[0]):
                best = (end - start, i)
        return best[1] if best else None

    def handler_symbol(self, route):
        mod = self.index.get(route["handler_file"])
        if mod is None or not route.get("symbol"):
            return None
        name = route["symbol"]
        hits = [i for _, _, i in self.by_module.get(mod, ()) if self.symbols[i][2] == name or self.symbols[i][2].endswith("." + name)]
        return hits[0] if hits else None

    def route_tables(self, route):
        """-> ({table: set of modes}, how it was traced)."""
        touched = defaultdict(set)
        sym = self.handler_symbol(route)
        if sym is not None:
            reached = set(self.closure([sym], self.calls_out, 5))
            for name, refs in self.g["tables"].items():
                for mode in ("read", "write"):
                    for path, line in refs[mode]:
                        mod = self.index.get(path)
                        if mod is not None and self.enclosing(mod, line) in reached:
                            touched[name].add(mode)
            if touched:
                return touched, "calls"
        mod = self.index.get(route["handler_file"])
        if mod is None:
            return touched, "none"
        reached = {self.modules[i] for i in self.closure([mod], self.out, 1)}
        for name, refs in self.g["tables"].items():
            for mode in ("read", "write"):
                if any(path in reached for path, _ in refs[mode]):
                    touched[name].add(mode)
        return touched, "imports"

    def cycles(self):
        """strongly connected components of the import graph, tests left out."""
        nodes = [i for i in range(len(self.modules)) if not self.is_test(i)]
        keep = set(nodes)
        order, low, on, stack, out, counter = {}, {}, set(), [], [], [0]
        for root in nodes:
            if root in order:
                continue
            work = [(root, iter(sorted(self.out[root] & keep)))]
            order[root] = low[root] = counter[0]
            counter[0] += 1
            stack.append(root)
            on.add(root)
            while work:
                node, it = work[-1]
                advanced = False
                for nxt in it:
                    if nxt not in order:
                        order[nxt] = low[nxt] = counter[0]
                        counter[0] += 1
                        stack.append(nxt)
                        on.add(nxt)
                        work.append((nxt, iter(sorted(self.out[nxt] & keep))))
                        advanced = True
                        break
                    if nxt in on:
                        low[node] = min(low[node], order[nxt])
                if advanced:
                    continue
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
                if low[node] == order[node]:
                    comp = []
                    while True:
                        top = stack.pop()
                        on.discard(top)
                        comp.append(top)
                        if top == node:
                            break
                    if len(comp) > 1:
                        out.append(sorted(comp))
        return sorted(out, key=len, reverse=True)


def group_of(path):
    parts = path.split("/")[:-1]
    if "src" in parts:
        cut = parts.index("src") + 2
        return "/".join(parts[:cut]) or "."
    return "/".join(parts[:2]) or "."


def tables_cell(touched, traced="calls"):
    if touched and traced != "calls":
        return "≈ " + tables_cell(touched)
    return ", ".join(f"{t} ({'/'.join(sorted(m[0].upper() for m in modes))})" for t, modes in sorted(touched.items())) or "—"


# ---------- markdown views ----------

def table(header, rows, empty):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    if not rows:
        lines.append("| " + " | ".join([empty] + ["—"] * (len(header) - 1)) + " |")
    return "\n".join(lines)


def view_modules(m):
    prod = [i for i in range(len(m.modules)) if not m.is_test(i)]
    fan_in = sorted(prod, key=lambda i: -len([s for s in m.inc[i] if not m.is_test(s)]))[:25]
    fan_out = sorted(prod, key=lambda i: -len(m.out[i]))[:15]
    between = defaultdict(int)
    for a, b in m.g["imports"]:
        if not m.is_test(a) and group_of(m.modules[a]) != group_of(m.modules[b]):
            between[(group_of(m.modules[a]), group_of(m.modules[b]))] += 1
    tangled = sorted(((a, b, n, between[(b, a)]) for (a, b), n in between.items() if a < b and (b, a) in between), key=lambda r: -min(r[2], r[3]))
    cycles = m.cycles()
    out = ["# Modules\n", "Import edges between source files, tests left out of the rankings.\n",
           "## Most depended on\n\nA change here reaches the most code. `impact <path>` lists what.\n",
           table(["File", "Imported by", "Imports"], [(f"`{m.modules[i]}`", len([s for s in m.inc[i] if not m.is_test(s)]), len(m.out[i])) for i in fan_in], "none"),
           "\n## Widest reach\n\nFiles that import the most; candidates for doing too much.\n",
           table(["File", "Imports", "Imported by"], [(f"`{m.modules[i]}`", len(m.out[i]), len(m.inc[i])) for i in fan_out], "none"),
           f"\n## Import cycles: {len(cycles)}\n",
           table(["Size", "Files"], [(len(c), ", ".join(f"`{m.modules[i]}`" for i in c[:8]) + (" …" if len(c) > 8 else "")) for c in cycles[:20]], "no cycle found"),
           "\n## Folders that depend on each other in both directions\n\nA layering that holds has none of these.\n",
           table(["Folder A", "Folder B", "A → B", "B → A"], [(f"`{a}`", f"`{b}`", x, y) for a, b, x, y in tangled[:25]], "none"),
           "\n## Dependencies between folders\n",
           table(["From", "To", "Imports"], [(f"`{a}`", f"`{b}`", n) for (a, b), n in sorted(between.items(), key=lambda kv: -kv[1])[:60]], "none"),
           "\n## External packages by use\n",
           table(["Package", "Files"], [(f"`{p}`", len(mods)) for p, mods in sorted(m.g["externals"].items(), key=lambda kv: -len(kv[1]))[:40]], "none")]
    return "\n".join(out) + "\n"


def view_entry_points(m):
    routes, how, declared = [], defaultdict(int), defaultdict(list)
    for r in m.g["routes"]:
        declared[(r["file"], r["line"], r["method"])].append(r)
    unique = [sorted(group, key=lambda r: len(r["path"]))[0] | {"paths": sorted({r["path"] for r in group}, key=len)} for group in declared.values()]
    unique.sort(key=lambda r: (r["path"], r["method"]))
    for r in unique:
        touched, traced = m.route_tables(r)
        how[traced] += 1
        handler = r["handler"] if r["handler_file"] == r["file"] else f"{r['handler']} · `{r['handler_file']}`"
        paths = f"`{r['paths'][0]}`" + (f" (also {', '.join(f'`{p}`' for p in r['paths'][1:])})" if len(r["paths"]) > 1 else "")
        routes.append((r["method"], paths, ", ".join(r["middleware"]) or "—", handler, tables_cell(touched, traced), f"`{r['file']}:{r['line']}`"))
    bare = [r for r in unique if not r["middleware"]]
    out = ["# Entry points\n",
           f"{len(unique)} route declarations ({len(m.g['routes'])} with every mount prefix), {len(m.g['jobs'])} background-work sites. Tables are marked R, W or R/W.",
           f"Tables were traced through call edges for {how['calls']} routes. For the other {how['imports'] + how['none']} the calls led nowhere, "
           "usually because of dependency injection or an inline handler, so the cell starts with ≈ and lists what the handler's file "
           "and the files it imports touch, which is more than the one handler does. A dash means nothing was found, not that nothing is touched.\n",
           "## Middleware applied before the routers\n\nIn source order; everything listed here runs for every route mounted after it.\n",
           table(["Where", "Middleware"], [(f"`{e['file']}:{e['line']}`", ", ".join(e["middleware"])) for e in m.g["app_middleware"]], "none found"),
           "\n## Routes\n\nMiddleware is listed in the order it runs: mount, router-level, then inline.\n",
           table(["Method", "Path", "Middleware", "Handler", "Tables reached", "Declared at"], routes, "no route found"),
           f"\n## Routes with no router-level or inline middleware: {len(bare)}\n\nPublic by design or missing a guard; the app-level list above still applies.\n",
           table(["Method", "Path", "Declared at"], [(r["method"], f"`{r['path']}`", f"`{r['file']}:{r['line']}`") for r in bare], "none"),
           "\n## Background work\n",
           table(["Kind", "Where", "Code"], [(j["kind"], f"`{j['file']}:{j['line']}`", f"`{j['text']}`") for j in m.g["jobs"]], "none found")]
    return "\n".join(out) + "\n"


def view_data(m):
    rows, shared = [], []
    for name, refs in sorted(m.g["tables"].items()):
        writers = sorted({p for p, _ in refs["write"]})
        readers = sorted({p for p, _ in refs["read"]} - set(writers))
        rows.append((f"`{name}`", len(writers), len(readers), ", ".join(f"`{p}`" for p in writers[:6]) + (" …" if len(writers) > 6 else "") or "—",
                     f"`{refs['schema'][0][0]}:{refs['schema'][0][1]}`" if refs["schema"] else "—"))
        groups = sorted({group_of(p) for p in writers})
        if len(groups) > 1:
            shared.append((f"`{name}`", len(writers), ", ".join(f"`{g}`" for g in groups)))
    unused = [f"`{n}`" for n, r in sorted(m.g["tables"].items()) if not r["read"] and not r["write"]]
    out = ["# Data\n", f"{len(m.g['tables'])} tables. Readers and writers are found from SQL text, query builders and ORM calls in product code; "
           "tests and migrations are left out. `table <name>` lists every site with its line.\n",
           "## Tables written from more than one folder\n\nNo single owner: check invariants, transactions and tenant scope at every writer.\n",
           table(["Table", "Writer files", "Folders"], sorted(shared, key=lambda r: -r[1]), "none"),
           "\n## Every table\n",
           table(["Table", "Writer files", "Read-only files", "Writers", "Defined at"], rows, "no table found"),
           "\n## Defined but not referenced in product code\n\n" + (", ".join(unused) or "none") + "\n"]
    return "\n".join(out) + "\n"


def view_frontend(m):
    server = [(r["method"], norm_path(r["path"]), r) for r in m.g["routes"]]
    called, orphans = set(), []
    for call in m.g["api_calls"]:
        hits = [i for i, (method, path, _) in enumerate(server) if method in (call["method"], "ALL", "ANY") and same_endpoint(norm_path(call["path"]), path)]
        called.update(hits)
        if not hits:
            orphans.append((call["method"], f"`{call['path']}`", f"`{call['file']}:{call['line']}`"))
    reached = {(server[i][2]["file"], server[i][2]["line"]) for i in called}
    uncalled = {}
    for method, _, r in server:
        if (r["file"], r["line"]) not in reached:
            key = (method, f"`{r['file']}:{r['line']}`")
            uncalled[key] = min(uncalled.get(key, r["path"]), r["path"], key=len)
    uncalled = sorted((method, path, where) for (method, where), path in uncalled.items())
    out = ["# Front end\n", f"{len(m.g['pages'])} client routes, {len(m.g['api_calls'])} API call sites, matched against {len(server)} server routes by method and path shape.\n",
           "## Client routes\n",
           table(["Path", "Component", "Declared at"], [(f"`{p['path']}`", p["component"] or "—", f"`{p['file']}:{p['line']}`") for p in m.g["pages"]], "none found"),
           f"\n## API calls with no matching server route: {len(orphans)}\n\nA third-party API, a path built at run time, or a call to an endpoint that does not exist.\n",
           table(["Method", "Path", "Called at"], orphans, "none"),
           f"\n## Server routes no client code calls: {len(uncalled)}\n\nWebhooks, public links and operational endpoints belong here. A client that builds its URLs in variables is invisible to this match, so treat the rest as a question, not as dead code.\n",
           table(["Method", "Path", "Declared at"], [(a, f"`{b}`", c) for a, b, c in uncalled], "none"),
           "\n## API call sites\n",
           table(["Method", "Path", "Called at"], [(c["method"], f"`{c['path']}`", f"`{c['file']}:{c['line']}`") for c in m.g["api_calls"]], "none found")]
    return "\n".join(out) + "\n"


def view_index(m, script):
    meta, g = m.g["meta"], m.g
    prod = sum(1 for i in range(len(m.modules)) if not m.is_test(i))
    lines = [f"# Code map: {meta['repo']}\n",
             f"Built {meta['built']} from commit `{meta['commit'][:12] or 'unknown'}`{' with uncommitted changes' if meta['dirty'] else ''}, engine `{meta['engine']}`.",
             (meta["note"] + "\n") if meta["note"] else "",
             table(["What", "Count"], [("Source files", f"{len(m.modules)} ({prod} outside tests)"), ("Import edges", len(g["imports"])),
                                       ("Functions, methods and classes", len(g["symbols"])), ("Call edges", len(g["calls"])),
                                       ("Routes", len(g["routes"])), ("Background-work sites", len(g["jobs"])), ("Tables", len(g["tables"])),
                                       ("Client routes", len(g["pages"])), ("API call sites", len(g["api_calls"])), ("Import cycles", len(m.cycles()))], "—"),
             "\n## Views\n",
             table(["File", "Read it for"], [("`modules.md`", "coupling, cycles, layering, the files a change reaches furthest from"),
                                              ("`entry-points.md`", "every route with its middleware, handler and tables; jobs, queues and schedules"),
                                              ("`data.md`", "which code reads and writes each table; tables with more than one owner"),
                                              ("`frontend.md`", "client routes, API calls, and the mismatches between client and server")], "—"),
             "\n## Asking the graph\n", "```bash", f"python3 {script} impact <map dir> <file>      # what depends on it, which routes reach it",
             f"python3 {script} route  <map dir> <text>      # middleware, handler and tables of matching routes",
             f"python3 {script} table  <map dir> <name>      # every read and write site, with line",
             f"python3 {script} deps|rdeps <map dir> <file>  # imports, one level or --depth N",
             f"python3 {script} symbol|callers|callees <map dir> <name>", "```",
             "\n## How far to trust it\n",
             "- The map is extracted by pattern from source text. It gives a file and line to open, not a proven fact: confirm in the code before citing it as evidence.",
             "- A missing entry proves nothing. Routes registered in a loop, SQL built from fragments, lowercase SQL keywords and dynamic imports are not seen.",
             "- Call edges come from name resolution. Edges between files that do not import each other are dropped, which removes most false matches and also every call made through dependency injection or an interface.",
             "- Type-only imports count as imports, so an import cycle may exist only at compile time.",
             "- It describes the commit above. `status` tells whether the code has moved since.\n"]
    return "\n".join(lines)


def cmd_build(args):
    repo = Path(args.repo).resolve()
    out = Path(args.out) if args.out else repo / "docs" / "remediation" / "code-map"
    graph = build_graph(repo, args.engine)
    out.mkdir(parents=True, exist_ok=True)
    (out / "graph.json").write_text(json.dumps(graph, separators=(",", ":")), encoding="utf-8")
    m = Map(graph)
    views = {"code-map.md": view_index(m, "<code-map skill>/scripts/codemap.py"), "modules.md": view_modules(m),
             "entry-points.md": view_entry_points(m), "data.md": view_data(m), "frontend.md": view_frontend(m)}
    for name, text in views.items():
        (out / name).write_text(text, encoding="utf-8")
    meta = graph["meta"]
    print(f"code map written to {out}")
    print(f"engine {meta['engine']}; {len(graph['modules'])} files, {len(graph['imports'])} imports, {len(graph['symbols'])} symbols, "
          f"{len(graph['calls'])} calls, {len(graph['routes'])} routes, {len(graph['tables'])} tables, {len(graph['api_calls'])} API call sites")
    if meta["note"]:
        print("note: " + meta["note"])


# ---------- status and queries ----------

def load(map_dir):
    path = Path(map_dir) / "graph.json" if Path(map_dir).is_dir() else Path(map_dir)
    if not path.exists():
        sys.exit(f"error: no code map at {path}; build one with `codemap.py build <repo>`")
    return Map(json.loads(path.read_text(encoding="utf-8")))


def map_state(repo, map_dir=None):
    """('missing' | 'fresh' | 'stale', message) for the map of a repo."""
    path = (Path(map_dir) if map_dir else repo / "docs" / "remediation" / "code-map") / "graph.json"
    if not path.exists():
        return "missing", f"missing: no code map at {path.parent}"
    meta = json.loads(path.read_text(encoding="utf-8"))["meta"]
    built = f"built {meta['built']} from {meta['commit'][:12] or 'an unknown commit'} with the {meta['engine']} engine"
    if "sources" in meta:
        now = fingerprint(repo, list_files(repo))
        then = meta["sources"]
        changed = sorted(f for f in now.keys() | then.keys() if now.get(f) != then.get(f))
        if not changed:
            return "fresh", f"fresh: {built}; no source file changed since"
        shown = ", ".join(changed[:5]) + (f" and {len(changed) - 5} more" if len(changed) > 5 else "")
        return "stale", f"stale: {built}; {len(changed)} source files added, removed or changed since: {shown}"
    # maps built before fingerprints: fall back to the commit
    head = (run(["git", "rev-parse", "HEAD"], cwd=repo) or "").strip()
    if meta["commit"] and head == meta["commit"] and not meta["dirty"]:
        return "fresh", f"fresh: {built}"
    return "stale", f"stale: {built}{' with uncommitted changes' if meta['dirty'] else ''}; the code is now at {head[:12] or 'unknown'}"


def cmd_status(args):
    state, message = map_state(Path(args.repo).resolve(), args.map)
    print(message)
    if state != "fresh":
        sys.exit(1)


def cmd_ensure(args):
    repo = Path(args.repo).resolve()
    state, message = map_state(repo, args.out)
    print(message)
    if state == "fresh":
        return
    if not args.engine:
        # keep the engine the map was built with, so a rebuild costs what the first build did
        previous = (Path(args.out) if args.out else repo / "docs" / "remediation" / "code-map") / "graph.json"
        args.engine = json.loads(previous.read_text(encoding="utf-8"))["meta"]["engine"] if previous.exists() else "auto"
    print(f"rebuilding with engine {args.engine}")
    cmd_build(args)


def show_modules(m, title, found, limit=80):
    print(f"{title}: {len(found)}")
    for i, depth in sorted(found.items(), key=lambda kv: (kv[1], m.modules[kv[0]]))[:limit]:
        print(f"  {'  ' * (depth - 1)}{m.modules[i]}")
    if len(found) > limit:
        print(f"  … {len(found) - limit} more")


def cmd_query(args):
    m = load(args.map)
    what, text = args.command, args.argument
    if what in ("deps", "rdeps", "impact"):
        hits = m.find_module(text)
        if len(hits) != 1:
            sys.exit(f"{len(hits)} files match `{text}`" + (": " + ", ".join(m.modules[i] for i in hits) if hits else ""))
        start = hits[0]
        print(m.modules[start])
        if what == "deps":
            found = m.closure([start], m.out, args.depth or 1)
            found.pop(start)
            show_modules(m, "imports", found)
            return
        found = m.closure([start], m.inc, args.depth or (1 if what == "rdeps" else 99))
        found.pop(start)
        if what == "rdeps":
            show_modules(m, "imported by", found)
            return
        tests = {i: d for i, d in found.items() if m.is_test(i)}
        show_modules(m, "depends on it, directly or not", {i: d for i, d in found.items() if i not in tests}, 60)
        print(f"tests that reach it: {len(tests)}")
        reach = {m.modules[i] for i in found} | {m.modules[start]}
        routes = [r for r in m.g["routes"] if r["handler_file"] in reach or r["file"] in reach]
        print(f"routes that reach it: {len(routes)} of {len(m.g['routes'])}")
        for r in routes[:60]:
            print(f"  {r['method']:6} {r['path']}")
    elif what == "route":
        hits = [r for r in m.g["routes"] if text.lower() in f"{r['method']} {r['path']} {r['handler']}".lower()]
        print(f"{len(hits)} routes match `{text}`")
        for r in hits[:40]:
            touched, traced = m.route_tables(r)
            print(f"\n{r['method']} {r['path']}    declared {r['file']}:{r['line']}" + (f", mounted {r['mounted_at']}" if r["mounted_at"] else ""))
            print(f"  middleware: {', '.join(r['middleware']) or 'none at router or route level'}")
            print(f"  handler:    {r['handler']} in {r['handler_file']}")
            print(f"  tables ({'via calls' if traced == 'calls' else 'via the handler file and its imports, coarse'}): {tables_cell(touched)}")
    elif what == "table":
        hits = [n for n in m.g["tables"] if text.lower() == n] or [n for n in m.g["tables"] if text.lower() in n]
        for name in hits[:8]:
            refs = m.g["tables"][name]
            print(f"{name}")
            for mode in ("schema", "write", "read"):
                print(f"  {mode}: {len(refs[mode])}")
                for path, line in refs[mode][:60]:
                    sym = m.enclosing(m.index.get(path, -1), line)
                    print(f"    {path}:{line}" + (f"  in {m.symbols[sym][2]}" if sym is not None else ""))
        if not hits:
            sys.exit(f"no table matches `{text}`")
    else:
        hits = [i for i, s in enumerate(m.symbols) if s[2] == text or s[2].endswith("." + text)]
        if not m.symbols:
            sys.exit("this map was built with the builtin engine and has no symbols; rebuild with cgr installed")
        if not hits:
            sys.exit(f"no symbol named `{text}`")
        for i in hits[:10]:
            mod, kind, name, start, end = m.symbols[i]
            print(f"{kind} {name}    {m.modules[mod]}:{start}-{end}")
            if what in ("callers", "callees"):
                edges = m.calls_in if what == "callers" else m.calls_out
                found = m.closure([i], edges, args.depth or 1)
                found.pop(i)
                for j, depth in sorted(found.items(), key=lambda kv: (kv[1], m.symbols[kv[0]][2]))[:60]:
                    print(f"  {'  ' * (depth - 1)}{m.symbols[j][2]}    {m.modules[m.symbols[j][0]]}:{m.symbols[j][3]}")
                print(f"  {what}: {len(found)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("repo")
    build.add_argument("-o", "--out")
    build.add_argument("--engine", choices=["auto", "cgr", "builtin"], default="auto")
    status = sub.add_parser("status")
    status.add_argument("repo")
    status.add_argument("map", nargs="?")
    ensure = sub.add_parser("ensure")
    ensure.add_argument("repo")
    ensure.add_argument("-o", "--out")
    ensure.add_argument("--engine", choices=["auto", "cgr", "builtin"], help="default: the engine of the existing map, else auto")
    for name in ("deps", "rdeps", "impact", "route", "table", "symbol", "callers", "callees"):
        query = sub.add_parser(name)
        query.add_argument("map")
        query.add_argument("argument")
        query.add_argument("--depth", type=int)
    args = parser.parse_args()
    {"build": cmd_build, "status": cmd_status, "ensure": cmd_ensure}.get(args.command, cmd_query)(args)


if __name__ == "__main__":
    main()
