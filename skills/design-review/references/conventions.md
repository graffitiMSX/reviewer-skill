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

## Human artifacts
Every stage leaves three things a person can use without rerunning it. The stage's markdown artifact stays the record; these make it inspectable.

**Run record.** `docs/remediation/work/<stage>/`, written as the stage runs, not reconstructed afterwards. `run.md` says what was run on what: date, repository commit, inputs, then one line per step with the command or agent, its exit status or outcome, and the file it produced; then each quality-gate item with pass or fail and what was sent back to an agent. Beside it, save every intermediate output as its own file under the name the skill gives: script output, the prompt handed to each agent, lists a script computed. Nothing a later step depends on lives only in the chat or in a scratch folder. No secrets, and no customer data copied out of the target system.

**Page.** After the gate passes, render the artifact for people:
```bash
python3 <design-review skill's directory>/scripts/page.py <stage> docs/remediation
```
with `<stage>` one of `code-map`, `review`, `conflicts`, `plan`, `tickets`, `dispatch`, `rereview`. It writes `docs/remediation/pages/<stage>.html`, a complete page to open in a browser: the whole document with folding sections, cross-linked IDs and filterable tables, under a dashboard computed from the same text. Never edit the page by hand; change the artifact and render again.

**Published page.** The same run writes `docs/remediation/pages/artifact/<stage>.html`, the form a claude.ai Artifact is published from. When the Artifact tool is available, ask once whether to publish it: the link is private by default, but these documents describe weaknesses in a real system, so sharing them is the user's call. On yes, publish that file with the title the script printed, and write the link into `run.md`; publishing the same file again updates the same link. Without the tool, or on no, say where the local page is and stop there.
**Keeping it current.** Every stage that reads code refreshes the map before using it or handing it to an agent:
```bash
python3 <code-map skill's directory>/scripts/codemap.py ensure <repo root>
```
It compares a hash of every source file with the one taken at build time and rebuilds only when a source file was added, removed or changed, committed or not; pipeline documents do not count. It writes nothing but the map folder, so it needs no approval. It keeps the engine the map was built with: seconds with builtin, a few minutes with cgr on a large repo, so say so before a cgr rebuild. Paste its output into the stage's `run.md`. When there is no map at all, `ensure` builds one; a stage that was not asked to map the code offers `/code-map` instead and carries on without one if the user prefers. A stage that maps code other than the checkout, such as a worktree, passes `-o <folder outside that worktree>` so the map is never committed with a fix.

When the skill passes a code map (`docs/remediation/code-map/`, built by `/code-map`), use it to find your way, then read the code.
- Read `code-map.md` and the view for your lens first: `modules.md` for architecture, `entry-points.md` and `data.md` for backend and security, `frontend.md` for front-end and UX. They replace the first pass of working out where the entry points are, what guards them and what they reach.
- Ask the graph instead of grepping for structure: `codemap.py route`, `table`, `impact`, `deps`, `rdeps`, `callers`, `callees`. The index lists them.
- The map points at evidence; it is not evidence. Open the file and line before citing anything, and cite the code, not the map. A route listed with no middleware is a question to check, not a finding.
- An absence proves nothing. The map misses routes registered in loops, SQL built from fragments and calls made through dependency injection; `code-map.md` lists its limits. Cover what it cannot see the way you would without it.
- The skill refreshed the map just before handing it to you. If you notice code the map does not match, trust the code and mention the mismatch under coverage.
- With no map, work as before.

## Finding IDs
`F-<LENS>-nnn` with LENS = ARC | BE | FE | UX | SEC, numbered in severity order within the lens. One issue per finding; a shared root cause is its own finding that links the others. When a finding belongs to another lens, note it in "Open questions / handoffs" instead of reporting it half-analyzed.

## Conflict IDs
`X-nnn`, for two or more findings whose remediations contradict each other. They are written by the `conflict-reviewer` agent in `design-review-conflicts.md`, never by a lens, and each one cites the `F-<LENS>-nnn` findings involved. The conflict types, resolution kinds and format are in that agent's file.

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

## Scorecard

Every lens grades each of its aspects from 0 to 10, and the merged report adds a score per lens and one overall score. An aspect is one numbered check in the reviewer's "Checks" list, under that check's own name, so the same aspects are graded on every run and scores can be compared over time.

**Rubric.** Grade the application as it is today, not the effort behind it.

| Grade | Meaning |
|---|---|
| 9–10 | Exemplary. No finding above Low; the controls are tested and observable. |
| 7–8 | Solid. Medium or Low findings only; no realistic path to serious harm. |
| 5–6 | Adequate with gaps. One High finding, or several Medium ones that compound. |
| 3–4 | Weak. Several High findings, or a Critical one with partial mitigation. |
| 0–2 | Unsafe or absent. An unmitigated Critical finding, or the control does not exist. |

**Caps.** A grade is a ceiling as well as a judgement, so a single number can never hide a serious finding:
- A Confirmed or Likely Critical finding caps its aspect at 3. A Confirmed or Likely High caps it at 6.
- A finding that is only Needs verification caps one band higher, Critical at 5 and High at 7, and the row says what to verify.
- A finding caps the aspect its defect sits in, and the `Findings` column lists only those. Every finding ID written anywhere in a row counts against that row. So when another aspect only touches a finding, for example Testing noting that a Critical defect has no test, describe it in words there and leave the ID out.
- Use `n/a` when the system does not have the aspect at all, such as AI-specific risk with no AI surface. Use `not assessed` when it could not be inspected. Neither counts in any average. Never grade what was not looked at.

**Evidence.** Each grade carries a one-line reason and the finding IDs that pulled it down. A grade of 8 or more names the strength that earned it.

**Gauge.** Ten segments, one filled per point: `▰▰▰▰▰▰▰▱▱▱ 7/10`. A decimal score fills the rounded number of segments and prints the decimal: `▰▰▰▰▰▰▱▱▱▱ 6.3/10`.

**Lens score.** The mean of the lens's graded aspects, to one decimal, capped at 4.0 while the lens has a Confirmed or Likely Critical finding and at 6.5 while it has a Confirmed or Likely High.

**Overall score.** The mean of the lens scores for the lenses that ran, to one decimal, under the same two caps applied across every lens. Label it Excellent from 9, Good from 7, Fair from 5, Poor from 3, and Critical below that. State which lenses it covers; a run of fewer than five lenses is a partial score and must say so, for example "partial: security only". Show the arithmetic and name any cap that applied.

The skill's `scripts/scorecard.py` recomputes every lens score and the overall score from the aspect grades, and rejects a grade above its cap. Its output is the scorecard section of the merged report, so the published numbers never depend on a model's arithmetic.

Lens scorecard, placed right after the executive assessment:

```
| Aspect | Grade | Gauge | Why | Findings |
|---|---|---|---|---|
| Idempotency and retries | 4 | ▰▰▰▰▱▱▱▱▱▱ 4/10 | Checkout has no idempotency key and the client retries POSTs | F-BE-001, F-BE-008 |

Lens score: ▰▰▰▰▰▱▱▱▱▱ 5.1/10 (mean of 8 aspects 5.4, capped at 6.5 by F-BE-003, High)
```

## Per-lens report structure
1. Executive assessment (risk, strengths, unknowns, three most important actions)
2. Scorecard: every aspect graded, then the lens score
3. Lens-specific map or inventory
4. Prioritized findings
5. Lens-specific tables (see each agent)
6. Test plan: missing tests mapped to findings
7. Open questions, assumptions and handoffs to other lenses
8. Prioritization matrix `| Rank | Finding | Severity | Confidence | Likelihood | Impact | Effort | Next step |`

## Merged report (produced by the skill)
Executive assessment across lenses (overall risk, recurring strengths, major unknowns, five most important actions with finding IDs) → scorecard (the overall score with its gauge, label and arithmetic; one row per lens `| Lens | Score | Gauge | Weakest aspect | Findings behind it |`; then every aspect from every lens in one table, lowest grade first) → system map (from ARC, plus SEC trust boundaries) → cross-lens root causes (one entry per shared cause, primary finding named, other IDs linked) → combined prioritization matrix (every finding from every lens, ranked by risk reduction per effort, security, data-integrity and revenue first) → handoffs and open questions (each handoff marked answered / partial / open) → per-lens sections concatenated by the skill's shell step under `# Lens: <name>` (a model never re-emits them).
