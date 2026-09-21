---
name: dispatch-fixes
description: Group open remediation GitHub issues into low-conflict batches, write an agent brief per group, dispatch fix-agent coding agents on isolated branches, then drive integration — validate PRs, ask before merging into the working branch, promote to stage, verify, comment on and close issues. Use when the user wants the remediation issues implemented, says "dispatch agents", "fix the issues", "start working the backlog", or asks to promote fixes to stage. Stage 4 of the remediation pipeline (design-review → action-plan → plan-to-issues → dispatch-fixes).
---

# Dispatch Fixes

Stage 4 of the remediation pipeline. Inputs: the open issues from `/plan-to-issues`, `docs/remediation/action-plan.md` and `tickets.md`. Output: `docs/remediation/dispatch.md` (groups, briefs, status table), plus branches and PRs. You are the coordinator: agents write code, you validate and gate every promotion.

## 1. Gather

```bash
gh issue list --state open --limit 200 --json number,title,labels,milestone,body
git branch -r
```
Determine the **default working branch** (`develop` if it exists, else the repo default) and whether `stage` exists. Read branch conventions, CI rules and review policy from CLAUDE.md, CONTRIBUTING and `.github/`. Do not invent scope, owners or acceptance criteria; take them from the issues and the plan.

## 2. Group

Put issues together only when they share an implementation boundary (same service, module, table, queue, root cause or enabling capability) **and** have compatible deploy and rollback needs, low merge-conflict risk and one coherent test strategy. Keep apart issues that need different expertise, have conflicting migrations, need separate risk gates, or depend on unfinished work. One group = one focused agent = one reviewable PR; split oversized groups into sequential batches.

Write `docs/remediation/dispatch.md` using `references/agent-brief.md`: one group record and one brief per group (`G-01`…, branch `agent/g-01-<short-desc>`), the dispatch order (parallel vs waiting on a prerequisite PR), and the status table:

`| Group | Issues | Branch | Agent PR | Working-branch merge | Stage PR | Stage verification | Issue comments | Closed |`

Statuses: Not started · In progress · PR open · Awaiting approval · Merged · Stage pending · Verified · Blocked · Failed.

Present the grouping and get approval before dispatching anything.

## 3. Dispatch

For each approved group spawn one `fix-agent` with `isolation: "worktree"`, all independent groups in the same turn. The prompt is the full brief plus repo path, default working branch and "Report using your completion format." Hold dependent groups until their prerequisite PR is merged into the working branch.

## 4. Integrate (per group, in dispatch order)

1. **Validate the PR.** Targets the working branch; every issue linked; scope matches the group; CI and reviews green; acceptance criteria met (read the diff, do not trust the report); no secrets or unrelated changes; migration, rollback, compatibility and observability addressed.
2. **Ask to merge.** "Group G-nn is ready. May I merge PR #n into `<branch>`?" with title, linked issues, test results and residual risks. Never merge without approval.
3. **Promote to stage.** Open or update the PR from the working branch into `stage` with the same traceability; merge per repo policy once checks pass. Never promote with failing checks, conflicts, unreviewed migrations or unverified criteria.
4. **Verify in stage.** Deploy completed; health checks; smoke or integration tests; expected logs, metrics and alerts present; original failure no longer reproducible where practical; no new error pattern; migrations and jobs completed. Record evidence, timestamp, commit SHA and limitations.
5. **Comment on each resolved issue** with the block in `references/agent-brief.md`.
6. **Close** only when the criteria are met, the change is in both the working branch and `stage`, staged behavior is verified, the comment is posted and no follow-up remains. Partially done: leave open, explain, link the follow-up.

Update the status table after every step so a reader can resume from the file alone.

## Safety

Never merge or close on an agent's word alone. Data migrations, security, payment and irreversible changes need explicit human review. Stop and report on divergent branches, failing tests, unsafe migrations or conflicting requirements. A newly discovered risk becomes a new issue, never silent scope growth.

## Final output

Grouping summary · one brief per group · dispatch order and dependencies · status table · verification and closure checklist · blockers and decisions that need the user.
