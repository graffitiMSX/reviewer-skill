# Lens re-review format

You are re-reviewing one lens of an application that was reviewed before. Your job is to say what is true **now** and grade it, so the earlier grades can be compared with the current ones. Follow the design-review conventions for rules, severity, confidence labels and the scoring rubric. Read-only.

## Method

1. Read your lens's section of the baseline review: its findings, and its scorecard if it has one.
2. For every baseline finding, open the code it cites and decide its status today. Then read the code that changed in your area since the baseline commit, looking for problems the changes introduced.
3. Grade every aspect of your lens as it stands now.

## Statuses

| Status | Meaning |
|---|---|
| Fixed | The defect is gone in the current code. Cite the file and symbol that prove it, and the commit or pull request if you can find it. |
| Partially fixed | Part of it is gone. Say precisely what remains. |
| Open | Unchanged. |
| Regressed | Worse than at the baseline. |
| Accepted | A documented decision not to fix it. Cite the decision. The risk still exists, so it stays listed under open findings. |
| Not verifiable | The proof is in production or at runtime. Say exactly what to check and where. |

A closed issue or a merged pull request is a pointer to where a fix should be, never proof that it is there. Give every baseline finding exactly one status; do not skip the awkward ones.

## Report, in this order

Use these exact table headers. A script reads them.

### 1. Summary
Four or five lines: counts by status, the biggest improvement, the biggest remaining risk, and anything new or regressed.

### 2. Baseline grades
One row per numbered check of your lens, with the same aspect names as your scorecard.

```
| Aspect | Baseline grade | Source |
|---|---|---|
| Idempotency and retries | 3 | reconstructed |
```

`Source` is `scorecard` when the baseline review graded the aspect, and you copy that grade unchanged. It is `reconstructed` when the baseline has no scorecard: grade the aspect as it stood then, from the baseline findings alone, with the same rubric and caps. Use `n/a` or `not assessed` where they apply.

### 3. Scorecard
The current grades, in the standard design-review scorecard table, ending with the lens score:

```
| Aspect | Grade | Gauge | Why | Findings |
|---|---|---|---|---|
| Idempotency and retries | 6 | ▰▰▰▰▰▰▱▱▱▱ 6/10 | Checkout is now behind a kill switch; no key yet | F-BE-008 |
```

Cite only findings that still weigh on the aspect: Open, Partially fixed, Regressed, Accepted, Not verifiable and new ones. A Fixed finding no longer caps anything.

### 4. Finding status
Every baseline finding of your lens, in the baseline's order.

```
| Finding | Severity | Status | Evidence now | Fixed by |
|---|---|---|---|---|
| F-BE-001 | Critical | Partially fixed | `CreateCheckout.ts:88` now persists `external_id`; webhooks still unresolved for old rows | #600 |
```

`Severity` is the finding's severity **today**: what a reviewer seeing this code for the first time would give it. Do not keep the baseline severity for the sake of comparability; the comparison is only fair when the current side is graded like a fresh review. If a partial fix or a new containment lowered it, give the new severity and say so in the evidence. Apply a containment evenly: a kill switch that lowers one finding lowers every finding behind the same switch.

### 5. Open findings
One heading per finding that is not Fixed, in the short form below. The heading format matters: it is how the scores are capped.

```
### F-BE-001 [High] Subscriptions never linked to the gateway
- **Confidence**: Confirmed
- **Status**: Partially fixed
- **What remains**: ...
- **Evidence**: paths, symbols, lines
- **Next step**: the smallest change that closes it
```

### 6. New findings since the baseline
Problems introduced or exposed by the changes, in the full design-review finding format, numbered after the baseline's highest ID for your lens. Mark each `- **Status**: New`. If you looked and found none, write that.

### 7. What would raise each aspect
One line per aspect graded below 7: the smallest set of findings to close to reach the next band.
