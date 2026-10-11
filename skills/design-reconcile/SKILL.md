---
name: design-reconcile
description: Check the lens reports of a design review against each other for contradicting remediations — a fix from one lens that undoes, blocks or duplicates a fix from another, incompatible changes to the same code, fix orders that loop — and resolve each into one remediation or a decision for the team. Use whenever the user asks whether the review's recommendations conflict or contradict, wants to cross-check or reconcile the lenses, worries about circular fixes or fixes reopening each other's issues, or is about to plan work from a review with more than one lens. Runs between design-review and action-plan in the remediation pipeline.
---

# Design Reconcile

An optional step between stages 1 and 2 of the remediation pipeline. Each lens of `/design-review` works alone, so two lenses can prescribe fixes that cannot both hold: security shortens a session that UX wants kept alive, or two lenses redesign the same function differently. Planned as written, those fixes reopen each other's findings. This skill reads all the lens reports together and produces `docs/remediation/design-review-conflicts.md`, which `/action-plan` reads alongside the review. Conflicts are numbered `X-nnn` and cite the `F-<LENS>-nnn` findings involved.

It reads reports and code and writes one file. It never edits the lens reports, the plan, issues or code.

## Steps

1. **Locate the reports.** Default: the per-lens files `docs/remediation/design-review-<lens>.md`, or the merged `design-review.md` when they are gone. If there is no review, say so and offer `/design-review`. With a single lens there is nothing to cross-check between lenses; say so, and run only if the user wants the check inside that lens. If an `action-plan.md` already exists, mention it: a conflict found now means some of its actions need revisiting. If the code has changed a lot since the review, say that the reviewer will flag findings that are already fixed, and that `/design-rereview` is the way to refresh them.
2. **List the shared ground.** Finding which fixes land on the same code is mechanical, so a script does it:
   ```bash
   python3 <this skill's directory>/scripts/conflicts.py candidates docs/remediation > <scratch>/shared-paths.md
   ```
3. **Delegate** to the `conflict-reviewer` agent (read-only). One agent, because it has to hold every report at once:
   ```
   Cross-check the design review of the application at <repo root>.
   Lens reports: <paths>. Shared-paths list: <path>.
   Context from the user: <constraints or priorities they stated, or "none">.
   Conventions: read <design-review skill's directory>/references/conventions.md first.
   Write your complete report to <output path>. Reply with only the summary, the conflict table and the decisions for the team.
   ```
   If the agent type is unavailable, use a general-purpose agent and tell it to read `../../agents/conflict-reviewer.md` (relative to this skill) first.
4. **Check the report.** Never judge the structure by eye:
   ```bash
   python3 <this skill's directory>/scripts/conflicts.py check docs/remediation/design-review-conflicts.md docs/remediation
   ```
   It exits non-zero when a conflict cites a finding that does not exist, lacks a resolution, or when the fix orders of all conflicts together form a cycle. Send those back to the agent; do not rewrite a resolution yourself.
5. **Present** the conflict table, any conflict marked live first since it is a defect in the code today, then the decisions that need the user, each with its options. Those are theirs to make: do not choose for them, and do not plan around an undecided one. Offer `/action-plan` next, which picks up the conflicts file.

## Quality gate

- `scripts/conflicts.py check` exits zero: every conflict names existing findings, has a resolution, and the fix orders contain no cycle.
- Every conflict states the concrete collision in the code or contract, and what happens when both fixes are applied as written.
- No finding is dropped by a resolution: a `prefer` says what the other finding gets instead.
- Trade-offs the code cannot settle are `decision`, with options, and are shown to the user.
- Identical fixes asked for by several findings are listed under plan once. Pairs that were checked and found compatible are listed, and a result of no conflicts is reported as such.
