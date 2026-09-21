---
name: design-review
description: Run an evidence-based design review of an application through five lenses — architecture, backend reliability, front-end, UX, security — each by a specialized read-only agent, then merge into one report with severity-ranked findings. Use whenever the user asks for an architecture, design, reliability, front-end, UX or security review or audit, wants to "find failure modes / races / idempotency problems / tenant-isolation gaps", asks "is this production-ready or secure", or wants to start the remediation pipeline (design-review → action-plan → plan-to-issues → dispatch-fixes). Accepts lens arguments such as `/design-review security`, `/design-review backend frontend`, `/design-review ux`, or none for all five.
---

# Design Review

Stage 1 of the remediation pipeline. Runs one or more lenses and produces `docs/remediation/design-review.md`, which `/action-plan` consumes. Findings carry the lens in their ID so they never collide and stay traceable: `F-ARC-nnn`, `F-BE-nnn`, `F-FE-nnn`, `F-UX-nnn`, `F-SEC-nnn`.

| Lens | Agent | Covers |
|---|---|---|
| `architecture` | `architecture-reviewer` | boundaries, coupling, data ownership, state machines, scalability shape, deployment safety, operability, test strategy |
| `backend` | `backend-reviewer` | idempotency, dual writes, concurrency, performance, resilience, queues, API contracts |
| `frontend` | `frontend-reviewer` | client code: state and data flow, submits, error states, forms, routing, performance, accessibility implementation, build config |
| `ux` | `ux-reviewer` | the experience: task flows and friction, navigation, feedback, error recovery, copy, consistency, onboarding and empty states, responsive behavior, trust |
| `security` | `security-reviewer` | authn, authz, tenant isolation, input handling, webhooks, secrets, client security, data protection, supply chain, AI risks |

## Steps

1. **Pick lenses and target.** Use the lenses the user named; default to all five, but drop `frontend` and `ux` when the repo has no client code and say so. Confirm repo root, focus area and output path (default above; create the folder). Note anything the user already knows (incidents, hot spots, missing telemetry) to pass on verbatim.
2. **Run the lenses in parallel**, one Agent call per lens in the same turn, each writing its own file `docs/remediation/design-review-<lens>.md`:
   ```
   Review the application at <repo root>. Focus: <area, or "whole system">.
   Context from the user: <notes or "none">.
   Conventions: read <this skill's directory>/references/conventions.md first.
   Write your complete lens report to <lens output path>. Reply with only the executive assessment and the prioritization matrix.
   ```
   If the Agent tool is unavailable, read the agent files in `../../agents/` (relative to this skill) and run the lenses yourself, one at a time.
3. **Merge** into `design-review.md` following the "Merged report" section of `references/conventions.md`: one executive assessment across lenses, the system map from the architecture lens, each lens section kept verbatim, one combined prioritization matrix, a cross-lens root-cause list (two lenses reporting the same cause: keep the deeper analysis, link the other ID), and the handoffs each lens raised. Keep the per-lens files; they are the evidence trail.
4. **Check the merged report** against the gate below; send gaps back to the lens agent rather than filling them yourself.
5. **Present** the executive assessment, the three most important actions and the combined matrix. Offer `/action-plan` as the next stage.

## Quality gate

- Every High or Critical finding has concrete evidence and a step-by-step failure or attack scenario.
- Backend lens: every dual-write candidate has a consistency analysis, every retriable mutation an idempotency assessment, every async flow a duplicate/order/poison/replay assessment. Security lens: every mutation and data read appears in the authorization matrix. UX lens: every critical flow was walked step by step, and screens it could not see are listed as Needs verification.
- Confidence labels on every finding; coverage and blind spots stated per lens.
- Handoffs between lenses were followed up, not dropped.
- Strengths listed; no secrets reproduced.
