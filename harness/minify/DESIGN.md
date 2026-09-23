# Minify harness — design

Force minified code emission from Claude Code, restore readable formatting with the
project's own formatter at turn end, and measure what the minified emission saved.

Status: approved design, not yet implemented.
Home: `harness/minify/` in this repo during development; moves to its own repo once the
tests pass.

## Goal

Cut output tokens spent on code by emitting it minified, and produce a defensible number
for how much that saved.

## Non-goals

- Reducing input tokens by keeping source minified on disk. Disk is formatted at every
  turn end by design.
- Enforcing compliance by rejecting writes. Enforcement is advisory (output style only).
- Counting the retry tax, session totals, or profile A/B. The log schema leaves room for
  them; the report does not show them. See Deferred.
- Installing formatters. The harness uses what a project already has, or steps aside.

## Decisions

| # | Decision | Chosen |
|---|---|---|
| 1 | What "minified" means | Fully minified one-liners where the language allows; dense fallback otherwise. Comments kept, at the shortest form that keeps necessary information |
| 2 | When the formatter runs | `Stop` hook, once per turn, on files touched that turn |
| 3 | How savings are measured | Counterfactual only: minified file vs the same file after formatting. No retry tax, no session ledger |
| 4 | What forces the style | Custom output style only. No denial hook |
| 5 | Packaging | `harness/minify/` here now; separate repo after tests |
| 6 | Turn-end formatter latency | Accepted (200 ms – 2 s) |

Decision 3 has a known blind spot, recorded deliberately: a failed `Edit` against a file
the formatter rewrote costs a re-read, and the report will not net that out. The report
can therefore read "saved 31%" on a session that cost more end to end. The event log
carries the fields needed to add that column later without re-instrumenting.

## Components

```
harness/minify/
  output-styles/minified.md      emission rules, symlinked into ~/.claude/output-styles/
  hooks/session-doctor.py        SessionStart  → inject per-language safety verdict
  hooks/log-write.py             PostToolUse   → append write events, never blocks
  hooks/format-turn.py           Stop          → format touched files, close the metric
  bin/minify-harness             CLI           → report, doctor
  bin/minread                    CLI           → dense-print a file for cheap reading
  lib/estimate.py                token estimator
  lib/detect.py                  formatter detection
  lib/classes.py                 language class table
  install.sh / uninstall.sh      symlinks + settings.json hook entries
  tests/                         round-trip, estimator, detection fixtures
```

## Flow, one turn

```
SessionStart
  session-doctor.py → "minify-safe: ts tsx js jsx json css | NOT safe: py | repo formatter-clean: yes"

turn
  Write src/api.ts     (minified)  ─┐  log-write.py appends one event per call
  Edit  src/api.ts     (minified)   ├─ ~/.claude/minify-harness/<slug>/<session>.ndjson
  Write src/card.css   (minified)  ─┘

Stop
  format-turn.py, for each file touched this turn:
    tok_min = estimate(current on-disk content)
    run detected formatter --write
    tok_fmt = estimate(content after formatting)
    append {turn, file, tok_min, tok_fmt, ...}
    churn check vs git pre-image → systemMessage if it spilled
  IDE shows formatted code
```

The counterfactual is measured, not synthesized: the real formatted file is the
comparison, and both sides go through the same estimator, so the ratio is stable even
where the absolute counts are not.

## Measurement unit

**Per file, per turn.** Three edits to `src/api.ts` in one turn produce one measurement:
the file's final minified state against its formatted state.

**Aggregation dedupes by file.** A file touched in turns 3 and 7 has two rows; summing
both would count the same file's tokens twice. `report` therefore takes the last row per
file and sums across distinct files. `report --turns` shows every row.

## Language classes

| Class | Extensions | Rule |
|---|---|---|
| `collapse` | ts, js, mjs, cjs, css, scss, json, svg | Collapse to one line where legal. `;` separators, no blank lines |
| `dense` | tsx, jsx, html, py, sh, bash, sql | No collapsing. 1-space indent, no blank lines, one statement per line |
| `exclude` | md, mdx, yaml, yml, toml, Dockerfile, docker-compose*.yml, .env*, lock files, `migrations/**` | Emit normally. Never minified |

Two hazards put languages in `dense` that could otherwise collapse:

- **Automatic semicolon insertion** (js, ts). Lines relying on ASI change meaning when
  joined, so `collapse` never joins across one; the round-trip test covers it.
- **Significant inline whitespace** (html, tsx, jsx). Whitespace between inline elements
  and inside JSX text nodes is rendered, so collapsing it is a visible behavior change,
  not a formatting change. These are `dense` for that reason, even though prettier
  formats them.

Comments survive in every class, compressed rather than deleted: `// retry: 429 only`,
not the removal of the reason.

## Event schema

One NDJSON file per session, outside the project so no `.gitignore` edit is needed:

```
~/.claude/minify-harness/<project-slug>/<session-id>.ndjson
```

Write event, appended by `log-write.py`. `chars` and `tok` measure the emitted payload
only — `content` for `Write`, `new_string` for `Edit` — not the whole file:

```json
{"k":"write","ts":"2026-09-23T14:02:09Z","turn":7,"tool":"Edit","file":"src/api.ts",
 "ext":"ts","class":"collapse","chars":1180,"tok":412,"style":"minified"}
```

Measurement event, appended by `format-turn.py`:

```json
{"k":"measure","ts":"2026-09-23T14:02:11Z","turn":7,"file":"src/api.ts","ext":"ts",
 "class":"collapse","ops":["Write","Edit","Edit"],"style":"minified",
 "formatter":"prettier@node_modules","formatter_ok":true,
 "chars_min":1180,"chars_fmt":1794,"tok_min":412,"tok_fmt":631,
 "churn_outside":0,"pre_image":"git:HEAD"}
```

`style` is read from the `outputStyle` key in settings at log time, so every row records
whether the harness was armed. Rows written with `style` unset are baseline rows.

## Token estimator

Local, offline, deterministic. `lib/estimate.py` splits source into runs and weights them:

| Run | Tokens |
|---|---|
| word `[A-Za-z_$][A-Za-z0-9_$]*` | `max(1, round(len / 4.2))` |
| digits | `max(1, round(len / 3))` |
| punctuation | `max(1, round(len / 1.6))` |
| whitespace run | `max(1, round(len / 6))` |
| newline | 1 each |

The sum is multiplied by a calibration constant `k` from `lib/calibration.json`, default
`1.0`. Uncalibrated output is labelled as such; ratios are reported regardless, because
both sides of every comparison use the same estimator and the bias cancels. `--chars`
prints raw byte counts, which need no estimator at all.

Calibrating is a manual, optional, one-time step: count a fixture set exactly once via
the Anthropic `count_tokens` API and write the fitted `k`. The harness never calls the
network at runtime.

## Formatter detection

`lib/detect.py`, first hit wins, never installs:

| Class | Order |
|---|---|
| ts, tsx, js, jsx, css, scss, json, html | `node_modules/.bin/prettier` → `node_modules/.bin/biome` → `package.json` `scripts.format` → `npx --no-install prettier` |
| py | `.venv/bin/ruff` → `.venv/bin/black` → `uv run ruff` |
| go | `gofmt` |
| rust | `rustfmt` |

No hit means the language is unsafe here: `doctor` reports it and the style must not
minify it.

## Guards

**Guard 1 — diff noise.** Formatting a file that was never formatter-clean rewrites lines
the session never touched. `session-doctor.py` runs one repo-level `--check` at session
start and injects the verdict:

| Repo state | Rule |
|---|---|
| formatter-clean | minify new and existing files |
| not clean | minify **new files only**; emit existing files normally |
| no formatter for the language | harness off for that language |

At turn end `format-turn.py` holds all three versions of the file, so churn is defined by
two diffs rather than one:

```
pre   = git show HEAD:<path>        (empty when untracked)
mine  = on-disk content before formatting
fmt   = on-disk content after formatting

my_lines    = changed line ranges in diff(pre, mine)
fmt_lines   = changed line ranges in diff(mine, fmt)
churn_outside = |fmt_lines \ my_lines|
```

It reports via `systemMessage` when `churn_outside` exceeds 20 lines or 30% of the file's
lines. Churn detection needs git; outside a git repo it is skipped and the session-start
verdict is the only protection.

**Guard 2 — formatter failure is a syntax check.** A broken one-liner makes the formatter
fail. `format-turn.py` records `formatter_ok: false` and surfaces the formatter's stderr
via `systemMessage`, so the next turn fixes it instead of committing it.

**Guard 3 — no silent permanence.** A file left minified because its formatter was missing
or failed is named in a turn-end message, and `format-turn.py` records the extension in
`~/.claude/minify-harness/<project-slug>/unsafe.json`. `session-doctor.py` reads that file
at every session start and excludes those extensions from its minify-safe list, so one
failure stops the harness from minifying that language again until the entry is removed
(`minify-harness doctor --clear <ext>`).

**Guard 4 — hook safety.** `log-write.py` and `format-turn.py` always exit 0, never emit a
blocking decision, and hold a per-session lock so a re-entrant `Stop` cannot double-format.
`log-write.py` does no formatting and no git calls, keeping it well under 50 ms.

## CLI

```
minify-harness report            # this session, deduped by file
minify-harness report --turns    # every measurement row
minify-harness report --all      # every session for this project, deduped per (session, file)
minify-harness report --by-lang
minify-harness report --chars
minify-harness doctor
minify-harness doctor --clear <ext>   # drop an extension from unsafe.json
```

```
SESSION 6dfd928c   style=minified   turns=7   2026-09-23

  file             tok_min  tok_fmt   saved
  src/api.ts           412      631     219   35%
  src/card.css          88      142      54   38%
  scripts/sync.py      203      249      46   18%
  ----------------------------------------------
  total                703     1022     319   31%

SAVED 31% on emitted code  (chars: 4,206 -> 6,117, 31%)
estimator: local regex-class, uncalibrated, ratio-stable
```

## minread

`bin/minread <file>` prints a dense form of a file — comments and blank lines dropped,
indentation collapsed — for orientation at lower input cost than `Read`.

Its constraint is structural and must be documented in the style, because a hook cannot
fix it: `PostToolUse` can only add context, never rewrite a tool result, so `Read` output
cannot be minified in place. And `Edit` matches exact strings from the real file, so
strings taken from `minread` output will not match.

`minread` is therefore only for files being surveyed rather than edited, or files that
will be replaced wholesale with `Write`. Reading a file with `minread` and then editing it
pays for both reads.

## Install

`install.sh` symlinks `output-styles/minified.md` into `~/.claude/output-styles/`, symlinks
`bin/minify-harness` and `bin/minread` into `~/.local/bin/` (already on `PATH`, where `rtk`
lives), and adds three hook entries to `~/.claude/settings.json` via
the `update-config` skill:

| Event | Matcher | Command |
|---|---|---|
| `SessionStart` | `*` | `session-doctor.py` (added alongside the existing `herdr-agent-state.sh`) |
| `PostToolUse` | `Write\|Edit` | `log-write.py` |
| `Stop` | `*` | `format-turn.py` |

The existing `PreToolUse` `rtk hook claude` entry is untouched. `uninstall.sh` reverses
all of it. Activation is `/output-style minified`; deactivation is `/output-style default`,
which leaves the logger running and the rows marked as baseline.

## Tests

| Test | Asserts |
|---|---|
| Round-trip equivalence | For each fixture: `format(minify(readable)) == format(readable)`. Equality means the minification was lossless. Fixtures for ts, tsx, css, json, py |
| ASI hazard | Fixtures that rely on automatic semicolon insertion are not collapsed |
| Estimator goldens | Fixed inputs produce fixed counts; ratios stay within 2% under `k` changes |
| Detection | Fixture projects: prettier-only, biome-only, ruff-only, none |
| Aggregation | A file touched in two turns is counted once by `report`, twice by `report --turns` |
| Churn guard | A dirty pre-existing file triggers the `systemMessage` threshold |
| Hook safety | Both hooks exit 0 on malformed input, missing git, and missing formatter |
| Exclusions | `exclude`-class files are never rewritten |

## Deferred

- Retry tax and session totals from `transcript_path`, which the `Stop` hook already gets.
- Profile A/B on one task, and aggregation grouped by the `style` field already logged.
- A `PreToolUse` density validator that denies non-compliant writes.
- Forcing `minread` through a `PreToolUse` `Read` hook.
