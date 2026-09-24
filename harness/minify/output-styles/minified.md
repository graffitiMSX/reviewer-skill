---
name: minified
description: Emit code minified so it costs fewer output tokens; the harness formats it back at turn end.
---

# Minified emission

Emit code as densely as the language allows. The harness normally runs the
project's own formatter on every file you touch at the end of the turn, which
restores readable formatting; spending output tokens on indentation and blank
lines buys nothing. When no formatter is available, the formatter fails, or the
repo is not clean, the code stays as emitted.

## Respect the session verdict

At session start the harness injects a line beginning `minify-harness:`. It names
the extensions that are safe here and whether the repo is formatter-clean. There
are three verdict states and four possible renderings:

- If the line is absent, no verdict is available (the hook is not installed or
  failed to run). Emit code normally — do not assume anything is safe.
- An extension it does not list as safe is either excluded entirely, has a
  formatter that does not work file-by-file, or is marked unsafe. Emit it
  normally — minifying it would leave it minified permanently.

Verdicts (by state):

- **Clean:** `repo formatter-clean: minify new and existing files` — minify all
  touched files.
- **Not clean:** `repo NOT formatter-clean: minify new files only` — minify new
  files only. Edits to existing files are emitted normally, because formatting
  those files would rewrite lines nobody touched.
- **Unknown (two renderings):**
  - `cleanliness unknown: minify new files only` (common, when no per-file
    formatter can be probed)
  - `checked N of M, cleanliness unknown: minify new files only` (when the repo
    was too large and only a sample was checked; N and M are numbers)
  - Both render the same verdict: minify new files only.

## Collapse class

<!-- collapse: ts js mjs cjs css scss json svg -->

Collapse to one line wherever it stays legal. Use `;` separators, no blank lines, no
indentation. Never join lines that rely on automatic semicolon insertion — add the
explicit `;` instead, or leave the break in. The formatter normalizes indentation
and line breaks but does not restore blank lines or brace style, so removing them is
a permanent change to the file rather than a round trip.

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

Anything outside the two marker lists above is never minified — the default
behavior is to exclude. Examples include Markdown, YAML, TOML, Dockerfiles,
Makefiles, compose files, `.env*`, lock files, and anything under a `migrations/`
directory. Emit those exactly as you normally would.

## Comments

Keep them. Compress them. The shortest form that keeps the necessary information:
`// retry: 429 only`, not the deletion of the reason and not a full sentence. Drop
banner separators, restated type signatures and anything a reader can see from the
code itself.

## Prose

Say what changed and why it is correct, once, briefly. No preamble, no restating the
code in English, no summary of a summary.

## Reading files

`minread <file>` prints a file with comments, blank lines and indentation stripped,
which costs fewer input tokens than reading it whole. Use it to survey code you are
not about to edit. Do not source `Edit` strings from `minread` output — `minread`
re-indents the interior lines of multi-line strings, which changes their value, and
`Edit` fails loudly on a mismatch. More critically, do not use `minread` output as
the basis for rewriting a file with `Write` or any other tool — `Write` performs no
verification against the real file and would silently commit the corruption. Always
re-read the real file first before writing.
