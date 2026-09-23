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
extensions that are safe here and whether the repo is formatter-clean, using one of
three verdicts: `clean`, `NOT clean`, or `unknown`. Obey the verdict:

- If the line is absent, no verdict is available (the hook is not installed or failed
  to run). Emit code normally — do not assume anything is safe.
- An extension it does not list as safe has no formatter available. Emit it normally —
  minifying it would leave it minified permanently.
- `repo clean` means minify all touched files.
- `repo NOT clean` or `repo unknown` means minify new files only. Edits to existing files are
  emitted normally, because formatting those files would rewrite lines nobody touched.

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
