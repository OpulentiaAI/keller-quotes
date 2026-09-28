# Blinded workflow trajectory reconstruction

This is a retrospective analysis of the same 18 retained attempts on six development RFQs, not a new model evaluation or a regrading. It captures 406 delivered MCP calls and recent-message snapshots for all 18 workers. The snapshots are **not full session event histories**; the complete scoped MCP audits are retained separately. Recorded checkout, model and working-tree content hashes identify the historical configuration without substituting current HEAD. See the [trajectory procedure](mcp-trajectory-analysis.md) and [numerical-error analysis](blinded-price-variance-results.md).

## Aggregate gains concealed individual losses

All attempts used the same frozen ten-criterion rubric. Among the five baseline/matched case pairs unaffected by the alias invalidity, mechanical passes rose from 4/25 to 20/25 and judge passes from 17/25 to 21/25. The combined count rose from 21/50 to 41/50, but **24 criterion gains concealed four criterion losses**:

| Generated case | Baseline V / J passes | Matched V / J passes | Pass-to-fail criteria |
| --- | --- | --- | --- |
| `development-b01-q1` | 0/5 / 3/5 | 4/5 / 3/5 | J2 evidence, J3 derivation |
| `development-b01-q2` | 0/5 / 3/5 | 4/5 / 5/5 | None observed |
| `development-b02-q1` | 0/5 / 4/5 | 4/5 / 5/5 | None observed |
| `development-b02-q2` | 0/5 / 4/5 | 4/5 / 3/5 | J2 evidence, J3 derivation |
| `development-b02-q3` | 4/5 / 3/5 | 4/5 / 5/5 | None observed |

Every matched final price still fails V3. “None observed” means no loss against that baseline, not a correct quote or an all-pass. The original 0/18 all-pass result remains unchanged. Six startup-invalid attempts and the one alias-invalid attempt remain in the attempted denominator; the comparator reports them as **not comparable**, not regression-free.

## What changed in the two failing trajectories

Both baseline workers withheld a final price after blocked precise-price lookups and unresolved physical comparability. Their J2/J3 passes credited honest evidence-shortage handling, not successful pricing or completion. The matched workers could retrieve the historical prices and pages, then submitted explicit prices despite acknowledging unresolved comparability. Producing a complete draft improved artifact criteria but did not establish a defensible price basis.

- In `development-b01-q1`, matched audit ordinals 29 and 30 supplied a source page and verified curve for a different component. Ordinal 44 copied its same-quantity unit into a final proposal without demonstrated material, revision or geometry comparability. The original judge failed J2/J3. Same customer, quantity and a similar finish description did not establish equivalence; the handoff also did not explain the displayed-versus-full-unit precision difference.
- In `development-b02-q2`, matched ordinals 12 and 17 supplied the curve and page; the page omitted the requested material/finish attributes. A recorded worker message acknowledged this gap but chose the source with no adjustment. Ordinal 23 persisted that exact-quantity transfer. The original J3 judgment identifies the mistake: an unknown process-price effect was treated as zero, rather than remaining a blocker.

The observed decisions and original criterion reasons support these mechanisms. The request and rubric hashes match, ruling out a reduced rubric or changed requested case as the explanation. The relevant matched traces contain no delivered tool errors, and both automatic/final extensions reconcile exactly, ruling out those failures as explanations for these particular J2/J3 losses. The source records were authentic; their applicability was not established. Original judgments were checked against the cited pages, curves and submitted derivations and left unchanged.

These observations do not prove that one code or prompt change caused the behavior: runtime/client conditions differed and the workers are stochastic. A full shell/browser event history is unavailable. Missing engineering evidence remains an unresolved input, not a proved explanation of every numerical miss.

## Capture and learning changes

The private artifact analyzer verifies supplied byte hashes, retains observed timestamps and audit ordinals, links exact final responses without double-counting them, and references existing per-turn numerical diagnostics. Its matched comparison fails on **any** criterion loss, even if totals improve; changed request/rubric/population, invalid attempts or untrustworthy evidence cannot produce a regression-free verdict. This is a diagnostic check, not an alternative acceptance channel or original-execution attestation.

The supplied session-analysis approach was adapted as overview → recorded conversation → event timeline → targeted evidence → actionable change. The on-call method was applied as competing explanations → verified evidence → scoped candidate learning → one independent review → unchanged accepted guidance. Three candidates were independently accepted and checked for scope overlap before being added unchanged to the estimator skill:

1. Record an evidence-backed source-versus-request comparison before replacing a hold with an explicit analog price.
2. Keep unknown material/finish adjustments distinct from zero adjustments.
3. Explain displayed-versus-full-unit precision in analogy-based handoffs, not just exact reissues.

The candidate packet, reviewer verdicts, evidence references and duplicate dispositions are retained privately. These are **unvalidated candidate workflow changes**, not a demonstrated recovery of the lost criteria. No fresh quoting worker or confirmation evaluation ran in this analysis. A matched development rerun can test the procedure; accuracy or outperformance claims still require a clean, globally isolated independent confirmation set with the unchanged rubric. No target prices or retrospective diagnostics are fed to live blinded workers.
