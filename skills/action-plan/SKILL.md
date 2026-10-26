---
name: action-plan
description: Convert a design or reliability review report (or any list of findings) into a sequenced, implementation-ready remediation action plan with containment steps, scored priorities, work items, rollout and rollback, tests and observability. Use whenever the user has findings, audit results or a review and asks "what do we do about this", wants a remediation plan, backlog, roadmap or prioritization. Stage 2 of the remediation pipeline (design-review → action-plan → plan-to-issues → dispatch-fixes → design-rereview).
---

# Action Plan

Stage 2 of the remediation pipeline. Reads `docs/remediation/design-review.md` (or another findings source) and produces `docs/remediation/action-plan.md`, which `/plan-to-issues` turns into GitHub issues. Actions are numbered `A-001`, `A-002`, … and each cites the `F-<LENS>-nnn` findings it addresses (ARC, BE, FE, UX, SEC).

## Steps

1. **Locate the input.** Default is the review report above. If none exists, ask whether to run `/design-review` first or plan from findings the user pastes. Collect constraints the user states (SLOs, deadlines, capacity, release freeze, risk tolerance) and pass them on verbatim; the planner must not invent any. If `design-review-conflicts.md` sits next to the review (written by `/design-reconcile`), pass it too. If it is missing and the review has two or more lenses, mention that `/design-reconcile` can check the fixes against each other first, and carry on if the user does not want it.
2. **Delegate** to the `remediation-planner` agent (read-only):
   ```
   Repository: <repo root>
   Review report: <path>
   Conflict report: <path, or "none">
   Code map: <map folder and `<code-map skill's directory>/scripts/codemap.py`, refreshed with `ensure` just before, or "none">
   Recorded decisions: <path to the decisions digest, collected as in /design-review into docs/remediation/work/plan/decisions.md>
   Constraints from the user: <list, or "none given">
   Normalize the findings, validate the High and Critical ones against the code, then write the complete action plan to <output path>. Reply with only the executive action summary, the containment plan and the action prioritization table.
   ```
   If the Agent tool is unavailable, read `../../agents/remediation-planner.md` (relative to this skill) and follow it yourself.
3. **Check the plan** against the gate below; send gaps back to the agent.
4. **Present** the summary, the first-week actions and the decision log (what stakeholders must decide before some actions can start). Offer `/plan-to-issues` as the next stage. Each decision the stakeholders settle goes into `docs/remediation/decisions.md` as the next `D-nnn`, as in `/design-reconcile`, and the actions it blocked are updated; offer `/design-memory` for a copy other projects can find.
5. **Draft the decision records.** When the plan lists decision records to write, offer to draft them. On yes, write one file per entry to `docs/remediation/decision-drafts/`, in the repo's own record format when it has one (the digest names its files; copy their headings and numbering) and otherwise as `NNNN-short-title.md` with Status, Context, Decision, Options considered, Consequences and Evidence. Mark each `Status: proposed`. Show the list, then ask whether to move them into the repo's record folder (`docs/adr/` when it has none). Moving them changes the team's source tree, so wait for a yes; committing and the pull request stay with the team.

## Human artifacts

Follow "Human artifacts" in `../design-review/references/conventions.md`; it is part of the stage, not an extra. Keep the run record in `docs/remediation/work/plan/`: `run.md`, plus `prompt.md` (the prompt sent to the planner, with the user's constraints verbatim), `decisions.md` (the digest it read) and `gate.md`; the drafted records stay in `docs/remediation/decision-drafts/`. When the gate passes, render the page with `page.py plan docs/remediation`, tell the user where it is, and ask whether to publish it.

## Quality gate

- Every Critical or High finding is assigned to an action, explicitly accepted, or blocked by a documented decision.
- Every action has priority, effort, owner profile, dependencies, acceptance criteria, rollout and rollback.
- Data migrations include compatibility, backfill, validation and recovery; nothing is called reversible without a tested restore.
- Unknowns became time-boxed discovery tasks; no invented incidents, volumes, owners or deadlines.
- When a conflict report exists, every `X-nnn` is reflected: its resolved remediation is what the plan builds, its order is respected, and each `decision` is in the decision log blocking the actions that depend on it.
- The traceability table maps every `F-<LENS>-nnn` to `A-nnn` IDs.
- Every decision the architecture lens marked `record`, and every register entry the repo's records lack, is under decision records to write.
- No action reverses a recorded decision: `accepted` findings carry no action and appear with their revisit condition, `drift` findings have an action that restores the decision, and `revisit` findings are decision-log entries.
- The run record exists in `docs/remediation/work/plan/` and `pages/plan.html` was rendered from the final artifact.
