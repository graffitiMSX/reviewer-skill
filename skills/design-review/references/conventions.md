# Review conventions shared by all lenses

Every reviewer agent embeds a compact copy of these rules; this file is the reference the skill hands to agents and uses when merging.

## Rules
- Read-only: never modify code, config, data or external systems; never call production endpoints.
- Evidence over assumption: cite paths, symbols, lines, queries, config keys. Quote the minimum; redact secrets.
- Label confidence on every finding: Confirmed (seen in code) / Likely (strong inference) / Needs verification (say exactly what to check).
- State coverage and blind spots when the repo cannot be inspected fully.
- Smallest safe fix first; no rewrites unless incremental change cannot address the risk.
- No generic advice: name the signal, location, threshold, owner and response.
- Report what is designed well, not only defects.

## Finding IDs
`F-<LENS>-nnn` with LENS = ARC | BE | FE | UX | SEC, numbered in severity order within the lens. One issue per finding; a shared root cause is its own finding that links the others. When a finding belongs to another lens, note it in "Open questions / handoffs" instead of reporting it half-analyzed.

## Finding format
```
### F-LENS-nnn [Severity] Short title
- **Confidence**: Confirmed / Likely / Needs verification
- **Category**: lens-specific category
- **Evidence**: paths, symbols, lines, queries, config
- **Affected flow**: endpoint, screen, job, event, entity or dependency
- **Failure scenario** (or attack / user scenario): concrete step-by-step, with interleaving or timing where relevant
- **Impact**
- **Why existing controls are insufficient**
- **Recommended remediation**: smallest safe fix, then stronger options
- **Verification**: test, query, metric or experiment that proves the fix
- **Residual risk**
```

## Severity
Critical = severe data loss, broad compromise, irreversible financial impact or prolonged outage. High = material corruption, duplicate business side effects, cross-tenant exposure or major outage under realistic conditions. Medium = localized inconsistency, recoverable failures, significant inefficiency. Low = limited impact or defense-in-depth gap. Informational = trade-off or opportunity. Rate realistic impact and exploitability, not theoretical possibility.

## Per-lens report structure
1. Executive assessment (risk, strengths, unknowns, three most important actions)
2. Lens-specific map or inventory
3. Prioritized findings
4. Lens-specific tables (see each agent)
5. Test plan: missing tests mapped to findings
6. Open questions, assumptions and handoffs to other lenses
7. Prioritization matrix `| Rank | Finding | Severity | Confidence | Likelihood | Impact | Effort | Next step |`

## Merged report (produced by the skill)
Executive assessment across lenses → system map (from ARC) → per-lens sections kept verbatim → combined prioritization matrix (all lenses, ranked by risk reduction per effort, security and data-integrity first) → cross-lens root causes → open questions.
