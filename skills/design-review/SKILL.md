---
name: design-review
description: Run an evidence-based design review of an application through five lenses — architecture, backend reliability, front-end, UX, security — each by a specialized read-only agent, then merge into one report with severity-ranked findings, a 0–10 grade for every aspect and an overall score. Use whenever the user asks for an architecture, design, reliability, front-end, UX or security review or audit, wants to "find failure modes / races / idempotency problems / tenant-isolation gaps", asks "is this production-ready or secure", or wants to start the remediation pipeline (design-review → action-plan → plan-to-issues → dispatch-fixes → design-rereview). Accepts lens arguments such as `/design-review security`, `/design-review backend frontend`, `/design-review ux`, or none for all five.
---

# Design Review

Stage 1 of the remediation pipeline. Runs one or more lenses and produces `docs/remediation/design-review.md`, which `/action-plan` consumes. Findings carry the lens in their ID so they never collide and stay traceable: `F-ARC-nnn`, `F-BE-nnn`, `F-FE-nnn`, `F-UX-nnn`, `F-SEC-nnn`. Every lens also grades each of its aspects from 0 to 10, and the merged report gives a score per lens and one overall score; the rubric, caps and gauge format are in `references/conventions.md`.

| Lens | Agent | Covers |
|---|---|---|
| `architecture` | `architecture-reviewer` | boundaries, coupling, data ownership, state machines, scalability shape, deployment safety, operability, test strategy |
| `backend` | `backend-reviewer` | idempotency, dual writes, concurrency, performance, resilience, queues, API contracts |
| `frontend` | `frontend-reviewer` | client code: state and data flow, submits, error states, forms, routing, performance, accessibility implementation, build config |
| `ux` | `ux-reviewer` | the experience: task flows and friction, navigation, feedback, error recovery, copy, consistency, onboarding and empty states, responsive behavior, trust |
| `security` | `security-reviewer` | authn, authz, tenant isolation, input handling, webhooks, secrets, client security, data protection, supply chain, AI risks |

## Steps

1. **Pick lenses and target.** Use the lenses the user named; default to all five, but drop `frontend` and `ux` when the repo has no client code and say so. Confirm repo root, focus area and output path (default above; create the folder). Note anything the user already knows (incidents, hot spots, missing telemetry) to pass on verbatim.
2. **Run the lenses in parallel, three at a time.** At most three agents run at the same time, or the number the user gave ("max 5", "one at a time"). Each agent costs tokens and machine load at once, so the default stays modest. With more lenses than the limit, start the first batch in one turn and start the next lens as each one finishes. One Agent call per lens, each writing its own file `docs/remediation/design-review-<lens>.md`:
   ```
   Review the application at <repo root>. Focus: <area, or "whole system">.
   Context from the user: <notes or "none">.
   Conventions: read <this skill's directory>/references/conventions.md first.
   Write your complete lens report to <lens output path>. Reply with only the executive assessment, the scorecard and the prioritization matrix.
   ```
   A reviewer sometimes returns the whole report in its reply instead of writing the file. Save that reply to the lens path yourself, unchanged and in the report's section order, before merging: the scorecard script and the merge both read the files.
   If the Agent tool is unavailable, read the agent files in `../../agents/` (relative to this skill) and run the lenses yourself, one at a time.
3. **Merge in two steps.** First write only the cross-lens header to `design-review.md`, following the "Merged report" section of `references/conventions.md`: one executive assessment across lenses, the scorecard, the system map, a cross-lens root-cause list (two lenses reporting the same cause: keep the deeper analysis, link the other IDs), one combined prioritization matrix with every finding, and the handoffs marked answered or open. Delegate that to an agent when the lens files are long; it only needs the five files and the conventions. Then append the lens reports with the shell — never by re-emitting them, which costs a full copy of every lens report in output tokens and risks silent paraphrase:
   ```bash
   for l in architecture backend frontend ux security; do
     f=docs/remediation/design-review-$l.md
     if [ -f "$f" ]; then
       { printf '\n\n# Lens: %s\n\n' "$l"; cat "$f"; } >> docs/remediation/design-review.md
     fi
   done
   ```
   The scorecard section is computed, never written by hand. Reviewers grade aspects; the script does the arithmetic, checks every grade against its cap, and prints the section to paste after the executive assessment:
   ```bash
   python3 <this skill's directory>/scripts/scorecard.py docs/remediation
   ```
   It exits non-zero and lists the problems when a grade breaks its cap, a grade has no reason, or a lens has no scorecard. Send those back to the lens agent to regrade; do not edit a grade yourself.

   Keep the per-lens files; they are the evidence trail.
4. **Check the merged report** against the gate below; send gaps back to the lens agent rather than filling them yourself.
5. **Present** the overall score with its gauge and label, the lens scores, the executive assessment, the three most important actions and the combined matrix. Say plainly when the score is partial because fewer than five lenses ran. Offer `/action-plan` as the next stage.

## Quality gate

- Every High or Critical finding has concrete evidence and a step-by-step failure or attack scenario.
- Backend lens: every dual-write candidate has a consistency analysis, every retriable mutation an idempotency assessment, every async flow a duplicate/order/poison/replay assessment. Security lens: every mutation and data read appears in the authorization matrix. UX lens: every critical flow was walked step by step, and screens it could not see are listed as Needs verification.
- Confidence labels on every finding; coverage and blind spots stated per lens.
- Handoffs between lenses were followed up, not dropped.
- Scorecard: `scripts/scorecard.py` exits zero, so no grade exceeds its cap and every grade has a reason. Every numbered check of every lens that ran appears with a grade, `n/a` or `not assessed`. The merged report carries the script's output unchanged, and a run of fewer than five lenses is labelled partial.
- Strengths listed; no secrets reproduced.
