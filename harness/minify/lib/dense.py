"""Dense rendering of a file for cheap reading. Comprehension only:
strings taken from this output will not match the real file, so Edit cannot use them.

WARNING: This module can alter multi-line string contents. The dense form re-indents
interior lines of triple-quoted strings, which changes the string value. The dense form
must not be used as a basis for rewriting a file with Write or any other tool — re-read
the real file first if you need to modify it."""
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
    """Strip comments, returning (text, unclosed_block_comment).

    When a block comment opener is found but no closer exists, the text after the
    opener is kept unstripped and unclosed_block_comment is True."""
    out, i, n = [], 0, len(text)
    quote = None
    unclosed_block = False
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
            if j < 0:
                # Block comment unclosed: keep remainder unstripped
                out.append(text[i:])
                unclosed_block = True
                i = n
            else:
                i = j + len(bclose)
            continue
        if line_tok and text.startswith(line_tok, i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        out.append(c); i += 1
    return "".join(out), unclosed_block

def _indent_level_map(lines):
    """Map distinct indentation levels to output depths.

    Collects all distinct leading-whitespace runs, orders by width, and maps the
    Nth distinct level to N spaces of output. Handles spaces, tabs, and mixed
    indentation with the same mechanism."""
    distinct_leads = set()
    for line in lines:
        if not line:
            continue
        # Collect the leading whitespace run
        lead_end = 0
        while lead_end < len(line) and line[lead_end] in (" ", "\t"):
            lead_end += 1
        lead = line[:lead_end]  # Can be empty string for lines with no indent
        distinct_leads.add(lead)

    # Sort by width (length of leading whitespace), with empty string first (depth 0)
    sorted_leads = sorted(distinct_leads, key=len)

    # Map each distinct lead to its output depth
    lead_map = {lead: i for i, lead in enumerate(sorted_leads)}
    return lead_map

def _py_densify_line(line, lead_map):
    """Convert a Python line to dense form using the indent map."""
    if not line:
        return ""

    # Extract leading whitespace
    lead_end = 0
    while lead_end < len(line) and line[lead_end] in (" ", "\t"):
        lead_end += 1
    lead = line[:lead_end]

    # Look up depth
    depth = lead_map.get(lead, 0)
    return (" " * depth) + line[lead_end:].strip()

def densify_status(text, path):
    """Dense form of `text` with unclosed-block-comment status.

    Returns: (dense_text, unclosed_block_comment)

    Excluded files come back unchanged. When a block comment opener has no closer,
    the text after the opener is kept unstripped and unclosed_block_comment is True.

    WARNING: This function can alter multi-line string contents by re-indenting
    their interior lines. The dense form must not be used as a basis for rewriting
    a file with Write or any other tool — re-read the real file first."""
    if classify(path) == "exclude":
        return text, False
    ext = _ext(path)
    text, unclosed_block = _strip_comments(text, LINE_COMMENT.get(ext), BLOCK.get(ext))
    lines = [l.rstrip() for l in text.splitlines()]
    lines = [l for l in lines if l.strip()]
    if ext in ("py",):
        lead_map = _indent_level_map(lines)
        out = [_py_densify_line(l, lead_map) for l in lines]
    else:
        out = [l.strip() for l in lines]
    result = "\n".join(out) + ("\n" if out else "")
    return result, unclosed_block

def densify(text, path):
    """Dense form of `text`. Excluded files come back unchanged.

    Returns: str (the densified text)

    WARNING: This function can alter multi-line string contents by re-indenting
    their interior lines. The dense form must not be used as a basis for rewriting
    a file with Write or any other tool — re-read the real file first."""
    result, _ = densify_status(text, path)
    return result
