---
name: plan-to-issues
description: Turn an approved remediation action plan into traceable GitHub issues that follow the target repo's own issue templates, labels and title conventions — drafts one ticket per action, shows a summary for confirmation, then creates the issues with gh in dependency order. Use when the user wants an action plan, backlog or findings turned into GitHub issues or tickets. Stage 3 of the remediation pipeline (design-review → action-plan → plan-to-issues → dispatch-fixes).
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
   grep -rlis "ISSUE_TEMPLATE\|issue template\|labels" docs CONTRIBUTING.md 2>/dev/null
   ```
   Make sure the active gh account is the one this repo expects (the project's CLAUDE.md usually says).

   Read the repo's issue conventions before drafting, because the tickets must follow them:
   - Every issue template: frontmatter `name`, `about`, `title` and `labels`, plus its headings. Issue forms (`*.yml`) give the same through `name`, `title`, `labels` and their fields.
   - Any doc that explains the setup, such as `docs/github_issues_setup.md`. It may define label colors, how `[BUG-000]`-style IDs are renumbered after creation, task-list hierarchy between Epic, Feature and Release issues, and Projects fields such as a High, Medium and Low priority.
   - Compare the labels the templates declare with the labels that exist. A declared label that does not exist yet is still the convention; it gets created, with its documented color.
2. **Draft** by delegating to the `ticket-writer` agent (it only writes the file):
   ```
   Action plan: <path>    Review report: <path>    Repository: <owner/repo>
   Existing labels: <list>    Milestones: <list or none>
   Issue templates: <paths, or none>    Convention docs: <paths, or none>
   Follow the repo's templates for type, labels, title pattern and headings.
   Fallback body template, only if the repo has no templates: <this skill's directory>/references/issue-template.md
   Write the tickets file to <repo>/docs/remediation/tickets.md in your required format. Reply with the summary table, proposed new labels and any ambiguities.
   ```
   If the Agent tool is unavailable, read `../../agents/ticket-writer.md` (relative to this skill) and draft it yourself.
3. **Check the draft.** Every actionable item has a ticket or an explicit split. IDs are preserved. Each ticket uses a repo template's labels, title pattern and headings. Only template-declared labels may be missing, and they are listed under "Labels to create" with colors. No proposed label is applied. No secrets. Then dry-run the parser, which validates the format and prints the creation order:
   ```bash
   python3 <this skill's directory>/scripts/create_issues.py docs/remediation/tickets.md
   ```
4. **Confirm before touching GitHub.** Show the user the repo, the ticket count, the count per template, the title pattern, the summary table, the labels to create with their colors, the milestone, and any proposed new labels (ask whether to add them). Creating issues is outward-facing: wait for an explicit yes.
5. **Create** with the script. It creates in dependency order and fills `{number}` in titles and headings with the zero-padded issue number, so `[TIM-{number}]` on issue #17 becomes `[TIM-017]`. It rewrites `T-nn` references to real `#numbers`, including forward ones in a final pass. It appends a `## Created issues` mapping to `tickets.md` after each success, so a rerun after a failure skips what already exists. `--fix-refs` finishes issues left with `T-nn` text or `000` numbers, and never overwrites an issue someone edited on GitHub:
   ```bash
   python3 <this skill's directory>/scripts/create_issues.py docs/remediation/tickets.md --create [--milestone "<name>"] [--create-missing-labels]
   ```
   To replace a run, for example after the repo's conventions change, create the new set first from a new tickets file that keeps the same `T-nn` IDs, then retire the old issues. Both retire modes preview by default and act only with `--yes`. They touch only open issues with no comments and a title the script wrote; the rest are listed and kept. Get an explicit yes before running either.
   - **Close (default choice):** closes each old issue as "not planned" and comments with its replacement's number. Works with triage rights.
     ```bash
     python3 <this skill's directory>/scripts/create_issues.py <old tickets.md> --close-created --superseded-by <new tickets.md> --repo <owner/repo> [--yes]
     ```
   - **Delete:** irreversible. In an organization repo it needs an owner to allow issue deletion (Organization settings, Member privileges); repo admin alone gets "Viewer not authorized to delete".
     ```bash
     python3 <this skill's directory>/scripts/create_issues.py <old tickets.md> --delete-created --repo <owner/repo> [--yes]
     ```
6. **Report** the created issues table (ticket → `#number` → title) and offer `/dispatch-fixes` as the next stage.
