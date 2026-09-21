---
name: action-plan
description: Convert a design or reliability review report (or any list of findings) into a sequenced, implementation-ready remediation action plan with containment steps, scored priorities, work items, rollout and rollback, tests and observability. Use whenever the user has findings, audit results or a review and asks "what do we do about this", wants a remediation plan, backlog, roadmap or prioritization. Stage 2 of the remediation pipeline (design-review → action-plan → plan-to-issues → dispatch-fixes).
---

# Action Plan

Stage 2 of the remediation pipeline. Reads `docs/remediation/design-review.md` (or another findings source) and produces `docs/remediation/action-plan.md`, which `/plan-to-issues` turns into GitHub issues. Actions are numbered `A-001`, `A-002`, … and each cites the `F-<LENS>-nnn` findings it addresses (ARC, BE, FE, UX, SEC).

## Steps

1. **Locate the input.** Default is the review report above. If none exists, ask whether to run `/design-review` first or plan from findings the user pastes. Collect constraints the user states (SLOs, deadlines, capacity, release freeze, risk tolerance) and pass them on verbatim; the planner must not invent any.
2. **Delegate** to the `remediation-planner` agent (read-only):
   ```
   Repository: <repo root>
   Review report: <path>
   Constraints from the user: <list, or "none given">
   Normalize the findings, validate the High and Critical ones against the code, then write the complete action plan to <output path>. Reply with only the executive action summary, the containment plan and the action prioritization table.
   ```
   If the Agent tool is unavailable, read `../../agents/remediation-planner.md` (relative to this skill) and follow it yourself.
3. **Check the plan** against the gate below; send gaps back to the agent.
4. **Present** the summary, the first-week actions and the decision log (what stakeholders must decide before some actions can start). Offer `/plan-to-issues` as the next stage.

## Quality gate

- Every Critical or High finding is assigned to an action, explicitly accepted, or blocked by a documented decision.
- Every action has priority, effort, owner profile, dependencies, acceptance criteria, rollout and rollback.
- Data migrations include compatibility, backfill, validation and recovery; nothing is called reversible without a tested restore.
- Unknowns became time-boxed discovery tasks; no invented incidents, volumes, owners or deadlines.
- The traceability table maps every `F-<LENS>-nnn` to `A-nnn` IDs.
