# Remediation pipeline

Claude Code skills and subagents that take an application from design review to verified fixes in four stages. Each stage writes an artifact into `docs/remediation/` in the target repo, and the next stage reads it, so findings stay traceable all the way to a merged pull request.

| Stage | Skill | Agents | Reads | Writes |
|---|---|---|---|---|
| 1 | `/design-review [lenses]` | `architecture-reviewer`, `backend-reviewer`, `frontend-reviewer`, `ux-reviewer`, `security-reviewer` (read-only, run in parallel) | repo | `design-review.md`, merged from one file per lens; findings `F-ARC/BE/FE/UX/SEC-nnn` |
| 2 | `/action-plan` | `remediation-planner` (read-only) | review + repo | `action-plan.md`; actions `A-nnn` |
| 3 | `/plan-to-issues` | `ticket-writer` (drafts only) | plan | `tickets.md`; tickets `T-nn`, then GitHub issues |
| 4 | `/dispatch-fixes` | `fix-agent` × N (one per group, own worktree) | open issues + plan | `dispatch.md`; groups `G-nn`, branches, PRs |

Stages 3 and 4 change external state (GitHub issues, merges, promotion to `stage`) and always stop for explicit approval first.

## Stage 1: design review

`/design-review` runs one agent per lens, each writing its own report, then merges them into a single document with one prioritization matrix. Pass lens names to narrow it: `/design-review security`, `/design-review backend frontend`. With no argument it runs all five and skips `frontend` and `ux` when the repo has no client code.

| Lens | Covers |
|---|---|
| `architecture` | boundaries, coupling, data ownership, state machines, scalability shape, deployment safety, operability, test strategy |
| `backend` | idempotency, dual writes, concurrency, performance, resilience, queues, API contracts |
| `frontend` | client code: state and data flow, submits, error states, forms, routing, performance, accessibility implementation, build config |
| `ux` | the experience: task flows and friction, navigation, feedback, error recovery, copy, consistency, onboarding, responsive behavior, trust |
| `security` | authn, authz, tenant isolation, input handling, webhooks, secrets, client security, data protection, supply chain, AI risks |

Every finding cites concrete evidence, carries a confidence label (Confirmed / Likely / Needs verification), a step-by-step scenario, the smallest safe fix and a verification step. Shared rules live in `skills/design-review/references/conventions.md`.

## Stages 2 to 4

- **`/action-plan`** normalizes the findings, validates the High and Critical ones against the code, scores risk transparently, and produces a four-layer plan (containment, near-term, hardening, long-term) of implementation-ready work items with tests, rollout, rollback and observability.
- **`/plan-to-issues`** drafts one ticket per action with the body template in `skills/plan-to-issues/references/issue-template.md`, shows a summary for confirmation, then creates the issues with `gh` in dependency order using `skills/plan-to-issues/scripts/create_issues.py`. The script rewrites `T-nn` references to real `#numbers`, records the mapping in `tickets.md`, and resumes safely after a failure. Run it without `--create` for a dry run.
- **`/dispatch-fixes`** groups open issues into low-conflict batches, writes an agent brief per group (`skills/dispatch-fixes/references/agent-brief.md`), dispatches one `fix-agent` per group in an isolated worktree, then drives integration: validate the PR, ask before merging into the working branch, promote to `stage`, verify, comment on and close issues.

## Layout

```
.claude-plugin/plugin.json   plugin manifest
agents/                      eight subagent definitions (frontmatter + system prompt)
skills/<name>/SKILL.md       four skills, each with references/ or scripts/ as needed
```

## Install

As a plugin:

```bash
claude --plugin-dir /path/to/this/repo
```

Or link into your user config:

```bash
for s in skills/*/; do ln -s "$PWD/$s" ~/.claude/skills/$(basename "$s"); done
mkdir -p ~/.claude/agents && ln -s "$PWD"/agents/*.md ~/.claude/agents/
```

## Notes

- All reviewer and planner agents are read-only (`Read`, `Grep`, `Glob`, `Bash`); only `fix-agent` can write, and it never merges, closes issues or touches `stage`.
- Agents use `model: inherit`. Set a specific model in an agent's frontmatter to run cheaper fix agents.
- The skills' eval workspaces (`skills/*-workspace/`) are git-ignored.
