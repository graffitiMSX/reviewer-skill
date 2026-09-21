---
name: plan-to-issues
description: Turn an approved remediation action plan into traceable GitHub issues — drafts one ticket per action using the standard issue body template, shows a summary for confirmation, then creates the issues with gh in dependency order. Use when the user wants an action plan, backlog or findings turned into GitHub issues or tickets, or says "create the issues", "open tickets for the plan", "file this as issues". Stage 3 of the remediation pipeline (design-review → action-plan → plan-to-issues → dispatch-fixes).
---

# Plan to Issues

Stage 3 of the remediation pipeline. Reads `docs/remediation/action-plan.md`, writes `docs/remediation/tickets.md`, and, only after explicit confirmation, creates GitHub issues. Tickets are `T-01`, `T-02`, … and each keeps its `A-nnn` parent action and `F-<LENS>-nnn` findings.

## Steps

1. **Resolve the repo context** (read-only):
   ```bash
   gh auth status
   gh repo view --json nameWithOwner,defaultBranchRef
   gh label list --limit 200 --json name,description
   gh api 'repos/{owner}/{repo}/milestones' --jq '.[].title'
   ls .github/ISSUE_TEMPLATE 2>/dev/null
   ```
   Make sure the active gh account is the one this repo expects (the project's CLAUDE.md usually says).
2. **Draft** by delegating to the `ticket-writer` agent (it only writes the file):
   ```
   Action plan: <path>    Review report: <path>    Repository: <owner/repo>
   Existing labels: <list>    Milestones: <list or none>    Issue templates: <paths or none>
   Body template: <this skill's directory>/references/issue-template.md
   Write the tickets file to <repo>/docs/remediation/tickets.md in your required format. Reply with the summary table, proposed new labels and any ambiguities.
   ```
   If the Agent tool is unavailable, read `../../agents/ticket-writer.md` (relative to this skill) and draft it yourself.
3. **Check the draft.** Every actionable item has a ticket or an explicit split; IDs preserved; labels exist or are listed as proposed; no secrets. Then dry-run the parser, which validates the format and prints the creation order:
   ```bash
   python3 <this skill's directory>/scripts/create_issues.py docs/remediation/tickets.md
   ```
4. **Confirm before touching GitHub.** Show the user the repo, the ticket count, the summary table, the labels and milestone to apply, and any proposed new labels (ask whether to create them). Creating issues is outward-facing: wait for an explicit yes.
5. **Create** with the script. It creates in dependency order, rewrites `T-nn` references to real `#numbers`, and appends a `## Created issues` mapping to `tickets.md` after each success, so a rerun after a failure skips what already exists:
   ```bash
   python3 <this skill's directory>/scripts/create_issues.py docs/remediation/tickets.md --create [--milestone "<name>"] [--create-missing-labels]
   ```
6. **Report** the created issues table (ticket → `#number` → title) and offer `/dispatch-fixes` as the next stage.
