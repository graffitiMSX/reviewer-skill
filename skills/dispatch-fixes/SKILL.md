---
name: dispatch-fixes
description: Group open remediation GitHub issues into low-conflict batches, write an agent brief per group, dispatch fix-agent coding agents on branches named by the repo's own conventions, then drive integration — validate PRs, ask before merging into the working branch, promote, verify, comment on and close issues. Use when the user wants the remediation issues implemented or promoted, or says "dispatch agents". Stage 4 of the remediation pipeline (design-review → action-plan → plan-to-issues → dispatch-fixes → design-rereview).
---

# Dispatch Fixes

Stage 4 of the remediation pipeline. You are the coordinator: agents write code, you validate and gate every promotion.

**Inputs**
- The open issues `/plan-to-issues` created. Filter them by the source label it applied, such as `source:design-review-2026-09`, so unrelated backlog stays out.
- The review and plan in the target repo at `docs/remediation/design-review.md` and `docs/remediation/action-plan.md`, or wherever `/action-plan` wrote them. Issue bodies cite these paths.
- The tickets file from `/plan-to-issues`, with its `## Created issues` mapping from `T-nn` to `#n`. It usually lives outside the repo; ask for its path if you do not have it. It gives each issue's parent action and dependencies.

**Output**
- `dispatch.md` with groups, briefs and the status table, written next to the tickets file. Do not write it into the target repo's working tree unless the user asks to version it; other sessions may be working in that checkout.
- Branches and PRs in the target repo.

## 1. Gather

```bash
gh issue list --state open --label "<source label>" --limit 300 --json number,title,labels,body
gh pr list --state merged --limit 30 --json number,baseRefName,headRefName,title
git branch -r
```

Read the repo's conventions from CLAUDE.md, CONTRIBUTING, `.github/` and workflow docs such as `docs/git_workflow.md`. Settle four things before grouping:

- **Working branch.** Every branch, PR and merge in this stage uses the branch where the team's work actually lands. Never assume the repo default, and never trust a documented branch that nothing merges into. Rank the evidence: the base branch of recently merged PRs, then the branch with recent commits, then the documented flow. State the branch you picked and the evidence for it, for example "`claude`, the base of the last 20 merged PRs, while the documented `dev` last moved six months ago". Ask the user only when the evidence conflicts or nothing has merged recently. Once picked, it is the base of every group branch and the target of every agent PR.
- **Promotion branch and its environment.** This is the branch the working branch is promoted to, such as `stage`, and the environment it deploys. In some repos that branch is production; the user or the project's docs say so.
- **Branch naming.** Typically `<prefix>/<issue-number>-short-description`, with the prefix chosen by issue type, for example `bugfix/` for bugs and `tech/` for spikes, tech debt and technical improvements.
- **Commit and PR titles.** Typically they start with the work-item ID, for example `[BUG-351] fix: reject typed JWTs`.

If the repo defines none of these, use the fallback: branch `agent/g-nn-<short-desc>` from the working branch you established, and PR title `G-nn: <description>`.

Do not invent scope, owners or acceptance criteria; take them from the issues and the plan.

## 2. Group

Put issues together only when they share an implementation boundary (same service, module, table, queue, root cause or enabling capability) **and** have compatible deploy and rollback needs, low merge-conflict risk and one coherent test strategy. Keep apart issues that need different expertise, have conflicting migrations, need separate risk gates, or depend on unfinished work. One group = one focused agent = one reviewable PR; split oversized groups into sequential batches. Tracking issues (Epic, Feature, Release) get no branch and are never dispatched.

Each group has a **lead issue**: the highest priority, then the lowest number. The group's branch and PR follow the repo convention for the lead issue, for example `bugfix/351-jwt-type-confusion` and PR title `[BUG-351] Reject typed JWTs as access tokens`. The PR body lists every other issue in the group.

Write `dispatch.md` using this skill's `references/agent-brief.md`: one group record and one brief per group (`G-01`…), the dispatch order (parallel vs waiting on a prerequisite PR) with the concurrency limit, and the status table:

`| Group | Lead issue | Issues | Branch | Agent PR | Working-branch merge | Promotion PR | Promotion verification | Issue comments | Closed |`

Statuses: Not started · In progress · PR open · Awaiting approval · Merged · Promotion pending · Verified · Blocked · Failed.

Present the grouping, the working branch, the promotion branch and its environment, and the naming you derived. Get approval before dispatching anything.

## 3. Dispatch

For each approved group spawn one `fix-agent` with `isolation: "worktree"`. At most three agents run at the same time, or the number the user gave ("max 5", "one at a time"). Each agent costs tokens and machine load at once, so the default stays modest. Start the first independent groups in one turn, up to the limit, and start the next group in dispatch order as each agent finishes. The prompt is the full brief: repo path, working branch, branch name, commit and PR title format, and "Report using your completion format." Hold dependent groups until their prerequisite PR is merged into the working branch.

## 4. Integrate (per group, in dispatch order)

1. **Validate the PR.** It targets the working branch, follows the branch and title conventions, links every issue, and matches the group's scope. CI and reviews are green. Acceptance criteria are met: read the diff, do not trust the report. No secrets or unrelated changes. Migration, rollback, compatibility and observability are addressed.
2. **Ask to merge.** "Group G-nn is ready. May I merge PR #n into `<working branch>`?" Include the title, linked issues, test results and residual risks. Never merge without approval.
3. **Promote.** Open or update the PR from the working branch into the promotion branch, with the same traceability. Ask before merging it, and say which environment it deploys. When the promotion branch is production, say so plainly. Never promote with failing checks, conflicts, unreviewed migrations or unverified criteria.
4. **Verify after promotion.** Deploy completed; health checks; smoke or integration tests; expected logs, metrics and alerts present; original failure no longer reproducible where practical; no new error pattern; migrations and jobs completed. Record evidence, timestamp, commit SHA and limitations.
5. **Comment on each resolved issue** with the block in `references/agent-brief.md`.
6. **Close** only when the criteria are met, the change is in both the working branch and the promotion branch, the promoted behavior is verified, the comment is posted and no follow-up remains. Partially done: leave open, explain, link the follow-up.

Update the status table after every step so a reader can resume from the file alone.

## Safety

Never merge or close on an agent's word alone. Data migrations, security, payment and irreversible changes need explicit human review. Stop and report on divergent branches, failing tests, unsafe migrations or conflicting requirements. A newly discovered risk becomes a new issue, never silent scope growth.

## Final output

Grouping summary · one brief per group · dispatch order and dependencies · status table · verification and closure checklist · blockers and decisions that need the user.

When a wave of fixes is promoted and verified, suggest `/design-rereview` for the lenses those fixes touched. It checks each finding against the promoted code and shows how the grades moved, which a list of closed issues cannot.
