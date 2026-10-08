# Remediation pipeline

Claude Code skills and subagents that take an application from design review to verified fixes in four stages. Each stage writes an artifact into `docs/remediation/` in the target repo, and the next stage reads it, so findings stay traceable all the way to a merged pull request.

| Stage | Skill | Agents | Reads | Writes |
|---|---|---|---|---|
| 1 | `/design-review [lenses]` | `architecture-reviewer`, `backend-reviewer`, `frontend-reviewer`, `ux-reviewer`, `security-reviewer` (read-only, run in parallel) | repo | `design-review.md`, merged from one file per lens; findings `F-ARC/BE/FE/UX/SEC-nnn` |
| 2 | `/action-plan` | `remediation-planner` (read-only) | review + repo | `action-plan.md`; actions `A-nnn` |
| 3 | `/plan-to-issues` | `ticket-writer` (drafts only) | plan | `tickets.md`; tickets `T-nn`, then GitHub issues |
| 4 | `/dispatch-fixes` | `fix-agent` × N (one per group, own worktree) | open issues + plan | `dispatch.md`; groups `G-nn`, branches, PRs |

Stages 3 and 4 change external state (GitHub issues, merges, promotion to whatever branch the target repo promotes to) and always stop for explicit approval first.

Once fixes have landed, `/design-rereview` closes the loop: it checks every earlier finding against the current code and compares the grades before and after.

The repo also carries the [minify harness](harness/minify/README.md), which is separate from the pipeline.

## Stage 1: design review

`/design-review` runs one agent per lens, each writing its own report, then merges them into a single document with one prioritization matrix. Pass lens names to narrow it: `/design-review security`, `/design-review backend frontend`. With no argument it runs all five and skips `frontend` and `ux` when the repo has no client code.

| Lens | Covers |
|---|---|
| `architecture` | boundaries, coupling, data ownership, state machines, scalability shape, deployment safety, operability, test strategy |
| `backend` | idempotency, dual writes, concurrency, performance, resilience, queues, API contracts |
| `frontend` | client code: state and data flow, submits, error states, forms, routing, performance, accessibility implementation, build config |
| `ux` | the experience: task flows and friction, navigation, feedback, error recovery, copy, consistency, onboarding, responsive behavior, trust |
| `security` | authn, authz, tenant isolation, input handling, webhooks, secrets, client security, data protection, supply chain, AI risks |

Every finding cites concrete evidence, carries a confidence label (Confirmed / Likely / Needs verification), a step-by-step scenario, the smallest safe fix and a verification step. Each lens also grades every aspect it checks from 0 to 10, shown as a gauge such as `▰▰▰▰▰▰▰▱▱▱ 7/10`, and the merged report adds a score per lens and one overall score. A Critical or High finding caps the grades it touches, and `skills/design-review/scripts/scorecard.py` computes the scores so the numbers never rest on a model's arithmetic. Shared rules live in `skills/design-review/references/conventions.md`.

## Stages 2 to 4

- **`/action-plan`** normalizes the findings, validates the High and Critical ones against the code, scores risk transparently, and produces a four-layer plan (containment, near-term, hardening, long-term) of implementation-ready work items with tests, rollout, rollback and observability.
- **`/plan-to-issues`** drafts one ticket per action following the target repo's own conventions: its `.github/ISSUE_TEMPLATE` types, labels, `[BUG-000]`-style titles and headings, plus any setup guide such as `docs/github_issues_setup.md`. It falls back to `skills/plan-to-issues/references/issue-template.md` when the repo has no templates. After a confirmation, `skills/plan-to-issues/scripts/create_issues.py` creates the issues with `gh` in dependency order. It fills work-item numbers after creation, rewrites `T-nn` references to real `#numbers`, creates missing template labels with their documented colors, records the mapping in `tickets.md` and resumes safely after a failure. Run it without `--create` for a dry run, and with `--fix-refs` to finish issues left with unresolved references.
- **`/dispatch-fixes`** groups open issues into low-conflict batches and writes an agent brief per group (`skills/dispatch-fixes/references/agent-brief.md`). It names branches, commits and PRs by the repo's own workflow, for example `bugfix/351-short-desc` and `[BUG-351] …`, and confirms the working and promotion branches before dispatching. It dispatches one `fix-agent` per group in an isolated worktree, then drives integration: validate the PR, ask before merging into the working branch, ask before promoting, verify, comment on and close issues.

## After the fixes: re-review

`/design-rereview [lenses]` measures what changed since the first review. Each lens starts from the earlier findings and the code that changed since the baseline commit, so it costs less than a fresh review. It gives every earlier finding a status, which is Fixed, Partially fixed, Open, Regressed, Accepted or Not verifiable, each backed by the current code rather than by a closed issue. It also looks for problems the changes introduced, re-grades every aspect, and compares before and after per aspect, per lens and overall.

`skills/design-rereview/scripts/compare.py` computes that comparison and refuses to pass while any earlier finding lacks a status. When the first review predates grading, the baseline grades are reconstructed from its findings with the same rubric and labelled as such. The report goes to `docs/remediation/design-rereview-<date>.md` and never overwrites the baseline.

## Minify harness

`harness/minify/` makes Claude Code emit code minified, formats it back with the project's own formatter at the end of the turn, and reports what the minified emission saved. It installs as an output style plus three hooks and has nothing to do with the remediation pipeline. See `harness/minify/README.md` for installing, arming and uninstalling it.

## Layout

```
.claude-plugin/plugin.json   plugin manifest
agents/                      eight subagent definitions (frontmatter + system prompt)
skills/<name>/SKILL.md       five skills, each with references/, scripts/ and evals/ as needed
harness/minify/              the minify harness: hooks, CLI, output style, tests
AGENTS.md                    instructions for coding agents working in this repo
CLAUDE.md                    imports AGENTS.md for Claude Code
```

## Install

As a plugin:

```bash
claude --plugin-dir /path/to/this/repo
```

Or link into your user config:

```bash
for s in skills/*/SKILL.md; do d=$(dirname "$s"); ln -s "$PWD/$d" ~/.claude/skills/$(basename "$d"); done
mkdir -p ~/.claude/agents && ln -s "$PWD"/agents/*.md ~/.claude/agents/
```

The links make this checkout the live source, so an edit here takes effect in every session.

## Notes

- All reviewer and planner agents are read-only (`Read`, `Grep`, `Glob`, `Bash`); only `fix-agent` can write, and it never merges, closes issues or pushes to the promotion branch.
- Agents use `model: inherit`. Set a specific model in an agent's frontmatter to run cheaper fix agents.
- Generated artifacts are git-ignored and never committed here: the skills' eval workspaces (`skills/*-workspace/`) and pipeline outputs such as reviews, re-reviews, action plans, tickets and dispatch logs. Those belong in the target repo's `docs/remediation/`.
