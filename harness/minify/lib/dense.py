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
