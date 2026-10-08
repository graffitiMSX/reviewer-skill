---
name: design-rereview
description: Re-review an application that already has a design review, to measure what changed since. Verifies in the current code whether each earlier finding is fixed, partly fixed, still open or regressed, looks for new problems in the code that changed, re-grades every aspect from 0 to 10 and compares the earlier grades with the current ones, per aspect, per lens and overall. Use whenever the user asks to re-review, re-audit or re-run a design review after fixes, wants to know "did the score improve", "what is still open from the review", "how are we doing since the audit", asks for a before/after, a progress or follow-up review, or wants to check that remediation work actually landed. Accepts lens arguments like `/design-review`, for example `/design-rereview security`.
---

# Design Re-review

Follows up `/design-review`. The first review said what was wrong and graded it. This one answers a narrower question: **what is true now, and how far did the grades move?** It produces `docs/remediation/design-rereview-<YYYY-MM-DD>.md` and never overwrites the baseline review.

It is cheaper than a full review because each lens starts from the earlier findings and the code that changed, instead of mapping the system again.

## Steps

1. **Find the baseline.** Default: `docs/remediation/design-review.md`, either the merged file or the per-lens files `design-review-<lens>.md` next to it. If there is none, say so and offer `/design-review` instead; there is nothing to compare against.
   - **Baseline commit.** Use the commit the report names in its header. Failing that, use the commit that first added the report (`git log --diff-filter=A --format=%H -- <report> | tail -1`). Failing that, ask. State which one you used and why.
   - **Current code.** The branch the team ships from, not whatever happens to be checked out. If other sessions use the checkout, review a clean worktree of that branch.
   - **Lenses.** Those the user named, limited to lenses the baseline actually covered. A lens with no baseline cannot be compared; offer a fresh `/design-review <lens>` for it.
2. **Scope the change.** `git log --oneline <baseline>..<current>` and `git diff --stat <baseline>..<current>`. Give each lens the list of changed paths in its area. Closed issues and merged pull requests are useful pointers to where a fix should be, and nothing more.
3. **Run the lenses in parallel, three at a time.** At most three agents run at the same time, or the number the user gave ("max 5", "one at a time"). Each agent costs tokens and machine load at once, so the default stays modest. With more lenses than the limit, start the first batch in one turn and start the next lens as each one finishes. One Agent call per lens with that lens's reviewer agent (`architecture-reviewer`, `backend-reviewer`, `frontend-reviewer`, `ux-reviewer`, `security-reviewer`), each writing `docs/remediation/rereview-<date>/design-rereview-<lens>.md`:
   ```
   Re-review the <lens> lens of the application at <path>, read-only.
   Baseline review: <path to the merged report or the lens file>, your lens's section. Baseline commit: <sha>. Current code: <branch> at <sha>.
   Changed since the baseline in your area: <paths, or "see git diff --stat <baseline>..<current>">.
   Read <this skill's directory>/references/rereview-format.md and <design-review skill's directory>/references/conventions.md first, and follow the format exactly.
   Write your report to <output path>. Reply with only the summary, the baseline grades, the current scorecard and the finding status table.
   ```
   A reviewer sometimes returns the whole report in its reply instead of writing the file. Save that reply to the lens path yourself, unchanged and in the report's section order, before running the comparison: the script reads the files.
   If a reviewer agent type is unavailable, use a general-purpose agent and tell it to read that reviewer's file in `../../agents/` first.
4. **Compute the comparison.** Never write the numbers by hand:
   ```bash
   python3 <this skill's directory>/scripts/compare.py --baseline <baseline file or folder> --current docs/remediation/rereview-<date>
   ```
   It recomputes both sets of scores with the design-review caps, prints the comparison section, and exits non-zero when a baseline finding has no status, a current grade breaks its cap, or a lens is missing a table. Send those back to the lens agent; do not edit a grade or a status yourself.
5. **Write the merged report.** A short header, then the script's output unchanged, then the lens reports appended by the shell rather than re-emitted:
   ```bash
   for l in architecture backend frontend ux security; do
     f=docs/remediation/rereview-<date>/design-rereview-$l.md
     if [ -f "$f" ]; then
       { printf '\n\n# Lens: %s\n\n' "$l"; cat "$f"; } >> docs/remediation/design-rereview-<date>.md
     fi
   done
   ```
   The header says, in this order: what was compared (baseline date and commit, current branch and commit, lenses), the overall score before and after, the three biggest improvements, what still holds the score down, anything that regressed or is new, and what was not verifiable from the code.
6. **Present** the overall before and after with gauges, the per-lens table, the status counts, regressions and new findings first, and the shortest list of fixes that would lift the score to the next band. Offer `/action-plan` for whatever is still open.

## What keeps a re-review honest

- **The code is the evidence.** A closed issue, a merged pull request or a commit message is a claim that something was fixed. Mark a finding Fixed only after reading the current code and seeing the defect gone, and cite where.
- **Every baseline finding gets a status.** Skipping the ones that are hard to check would quietly inflate the score. `Not verifiable` is a legitimate answer when the proof lives in production or at runtime; say exactly what to check.
- **Fixes can break things.** Read the changed code for new problems in the lens's area, and report them as new findings. A re-review that only confirms fixes misses regressions.
- **Same rubric, both sides.** Grade the current state with the design-review rubric and caps. When the baseline has no scorecard because it predates grading, reconstruct its grades from the baseline findings with the same rubric and label them reconstructed, so the comparison is like for like.
- **A partial comparison says so.** Comparing two lenses is not comparing the application. The script labels a partial score.

## Quality gate

- `scripts/compare.py` exits zero.
- Every baseline finding in each lens has exactly one status with current evidence; every Fixed cites the code that proves it.
- New findings and regressions are listed, or the lens says it looked and found none.
- The merged report carries the script's comparison unchanged and states the baseline and current commits.
