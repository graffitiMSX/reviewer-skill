# Fallback GitHub issue body template

Use this only when the target repo has no issue templates. When it has them, follow the chosen template's headings and append the sections below that it lacks: Traceability, Evidence, Acceptance Criteria, Verification Evidence, Rollout and Rollback, Residual Risk.

Fill every section. Write "None" instead of leaving a section empty. Keep `A-nnn` and `F-<LENS>-nnn` IDs verbatim so the ticket stays traceable to the plan and the review.

```markdown
## Summary

<!-- One or two sentences: the remediation and the expected outcome. -->

## Type and Priority

- Type: `bug | security | performance | reliability | feature | task | migration | test | documentation | discovery`
- Priority: `P0 | P1 | P2 | P3`
- Severity: `Critical | High | Medium | Low | Informational`
- Effort: `XS | S | M | L | XL`

## Traceability

- Parent action: `A-nnn` — Action title
- Related findings: `F-BE-nnn`, `F-SEC-nnn`
- Review reference: `docs/remediation/design-review.md`, section or heading
- Related tickets: `T-nn` (split siblings), or None

## Problem

<!-- The failure, risk, bottleneck or missing control, and why it matters. -->

## Evidence

- `path/to/file.ext:line-or-symbol` — relevant behavior.
- `path/to/migration.sql` — relevant or missing constraint.
- `path/to/test.ext` — existing coverage or missing scenario.
- Review evidence: report section.

## Scope

### Included

- Specific code, schema, infrastructure, test, observability, migration or documentation changes.

### Excluded

- Explicitly excluded work, to prevent scope growth.

## Implementation Notes

<!-- Constraints, invariants, compatibility requirements, preferred incremental approach. -->

## Dependencies

- Depends on: `T-nn`, or None.
- Blocks: `T-nn`, or None.
- Required decisions or approvals: list them, or None.

## Acceptance Criteria

- [ ] A precise functional or technical condition is satisfied.
- [ ] Duplicate, retry, timeout, concurrency or failure behavior is verified where relevant.
- [ ] Authorization and tenant-isolation behavior is verified where relevant.
- [ ] Database, event, queue, migration or compatibility requirements are verified where relevant.
- [ ] Regression tests cover the original failure scenario.
- [ ] Observability is added or updated where required.
- [ ] Rollout and rollback procedures are documented and validated.

## Verification Evidence

- Tests: exact suites or commands.
- Data checks: exact query, reconciliation report or invariant check.
- Runtime checks: dashboard, metric, trace, log or alert.
- Release checks: feature flag, migration, canary or rollback evidence.

## Rollout and Rollback

<!-- Deployment order, feature flags, migration safety, stop conditions, recovery method. -->

## Definition of Done

- [ ] Implementation reviewed and merged.
- [ ] Automated tests pass.
- [ ] Relevant failure-path tests pass.
- [ ] Observability and alerts are available.
- [ ] Documentation or runbook is updated.
- [ ] Verification evidence is attached or linked.
- [ ] Residual risk is recorded.

## Ownership

- Owner profile/team: `team-or-role`
- Suggested milestone: `milestone-or-release-phase`, or unknown

## Residual Risk

<!-- What remains unresolved, accepted or deferred. -->
```
