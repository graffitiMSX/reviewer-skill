# Agent instructions

This repo holds Claude Code skills, subagents and a harness. It is the source: `~/.claude/skills/<name>` and `~/.claude/agents/*.md` are symlinks into this checkout, so an edit here is live in every session at once.

## Layout

- `skills/<name>/SKILL.md`: one skill, with `references/`, `scripts/` and `evals/` beside it as needed.
- `agents/<name>.md`: one subagent, frontmatter plus system prompt.
- `harness/minify/`: the minify harness, with its own README, design and tests.
- `.claude-plugin/plugin.json`: plugin manifest.
- `README.md`: the user-facing description of all of the above.

## Rules

- **Keep skills and agents concise.** `SKILL.md` carries the workflow; detail that is needed only sometimes goes in `references/`. Explain why a rule exists instead of shouting it.
- **Models judge, scripts compute.** Grades, severities and statuses are a reviewer's judgement. Arithmetic, caps, cross-checks and anything that touches GitHub in bulk belong in a script under `scripts/`, and the skill's quality gate relies on that script's exit status.
- **Reviewer and planner agents stay read-only** (`Read`, `Grep`, `Glob`, `Bash`). Only `fix-agent` writes code, and it never merges, closes issues or pushes to a promotion branch.
- **A skill never changes external state without the user's approval.** Creating issues, merging, promoting and closing each stop and ask first.
- **Parallel agents are capped.** A skill that fans out agents runs at most three at a time unless the user gives another number, and says so in its steps.
- **Shared rules have one home.** Finding IDs, severity, confidence and the scoring rubric live in `skills/design-review/references/conventions.md`. Other skills and agents point to it; they do not restate it.
- **Keep the docs in step.** Adding, renaming or removing a skill or agent means updating `README.md` and the description in `.claude-plugin/plugin.json` in the same commit.

## Checks before committing

```bash
# every SKILL.md and agent file has valid YAML frontmatter with name and description
python3 - <<'PY'
import glob, sys, yaml
for f in glob.glob("skills/*/SKILL.md") + glob.glob("agents/*.md"):
    meta = yaml.safe_load(open(f).read().split("---")[1])
    assert meta.get("name") and meta.get("description"), f
print("frontmatter ok")
PY

# scripts still load
python3 -m py_compile skills/*/scripts/*.py

# harness tests
python3 -m unittest discover -s harness/minify/tests -t .
```

A change to a skill's wording is best checked by running the skill on a real repo and reading the output; `skills/<name>/evals/evals.json` holds the prompts and what to look for.

## Git

- Never commit generated artifacts: eval workspaces (`skills/*-workspace/`) and pipeline outputs such as reviews, re-reviews, action plans, tickets and dispatch logs. They are git-ignored; keep it that way. `docs/` holds the source prompts and is also ignored.
- Commit messages carry only the change description. No AI attribution trailers or links.
- Work on a branch; push or merge to `main` only when asked.
