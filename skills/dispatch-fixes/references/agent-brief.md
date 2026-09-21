# Group record, agent brief and closure comment templates

## Group record (one per group, in dispatch.md)

```text
Group ID: G-nn
Group title:
Goal:
Included issues: #n, #n
Excluded or deferred issues:
Related findings: F-<LENS>-nnn
Affected components:
Dependencies: (groups or PRs that must land first, or None)
Conflict risk: low | medium | high — why
Required expertise:
Branch name: agent/g-nn-<short-description>
Agent assignment: fix-agent
Implementation constraints:
Shared acceptance criteria:
Validation plan:
Promotion readiness conditions:
```

## Agent brief (the prompt handed to fix-agent)

```markdown
# Agent Brief: G-nn — Group title

## Goal
Implement the grouped fixes so that <risk> is removed or reduced without changing unrelated behavior.

## Issues
- #123 — Issue title
- #456 — Issue title

## Required behavior
- Business, data, security, reliability or performance invariants that must hold.

## Scope
### In scope
- Specific files, modules, services, schemas, tests, infrastructure, documentation.
### Out of scope
- Explicit exclusions.

## Implementation guidance
- Preserve backward compatibility where required.
- Handle retries, duplicates, concurrency, timeouts, partial failures and rollback where relevant.
- Do not weaken authorization or tenant isolation.
- Avoid unrelated refactoring.

## Tests and verification
- Unit, integration, contract, migration, concurrency, failure-path, security or load tests the issues require.
- The exact acceptance criteria that must pass.

## Branch and delivery
- Repository: <absolute path>
- Branch: `agent/g-nn-short-description`
- Base branch: <default working branch>
- Commit in reviewable units; open one PR targeting the base branch; link every issue.

## Completion report
Report using your completion format: files changed, tests executed and results, acceptance criteria status per issue, migration or rollout concerns, observability changes, known limitations and residual risks, PR number.
```

## Issue comment after staged verification

```markdown
Implemented in PR #<agent PR>.

- Group: G-nn
- Working-branch merge: PR #n or commit SHA
- Stage promotion: PR #n or commit SHA
- Verification: tests, checks, dashboard or smoke-test evidence, with timestamp
- Environment: stage
- Residual risk or follow-up: None, or explicit details
```
