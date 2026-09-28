# Blinded historical quote workflow: interim results

The completed expanded baseline and matched phase attempted **18 worker workflows on six distinct RFQs**: six baseline, six startup-invalid, and six matched attempts. **None passed all ten criteria.** Seven attempts were invalid and remain in the denominator. These are reconstructed frozen-snapshot historical-price workflows, not true backtests, current-cost tests or exact reissues. The [blinded evaluation contract](blinded-mcp-workflow-evaluations.md) defines the mechanical V1–V5 and independent J1–J5 criteria. Workers and judges used `codex/gpt-6-luna` at max reasoning with fast mode.

The frozen plan has 30 development and 30 confirmation cases. Only six development cases have been attempted; **24 development cases remain unrun, and no confirmation RFQ has run**. The >90% confirmation gate remains a future requirement of at least **28/30 original** all-ten-criterion persisted complete drafts on confirmation cases; held, missing and unjudged cases cannot be removed, and adjudications would be separate. The original judgments remain unchanged, with no adjudications. The gate is not met.

## Attempt ledger

Each cell gives passed mechanical criteria (V) / passed independent judgments (J), out of five each. `—` means no J verdict, not a pass. Startup-invalid attempts failed all five V checks and were unjudged. The matched invalid attempt retains its original V/J verdicts despite its invalid scope/audit alias.

| Development case | Baseline | Startup-invalid | Matched | Matched status |
| --- | ---: | ---: | ---: | --- |
| `development-b01-q1` | 0/3 | 0/— | 4/3 | V3 failed |
| `development-b01-q2` | 0/3 | 0/— | 4/5 | V3 failed |
| `development-b01-q3` | 4/3 | 0/— | 3/4 | **Invalid scope/audit alias**; V3 and V5 failed |
| `development-b02-q1` | 0/4 | 0/— | 4/5 | V3 failed |
| `development-b02-q2` | 0/4 | 0/— | 4/3 | V3 failed |
| `development-b02-q3` | 4/3 | 0/— | 4/5 | V3 failed |
| **Cohort total (six attempts each)** | **V 8/30; J 20/30; 0 all-pass** | **V 0/30; J unjudged; 6 invalid; 0 all-pass** | **V 23/30; J 25/30; 1 invalid; 0 all-pass** | **7 invalid overall** |

The five unaffected matched cases produced priced drafts, but **all five failed V3**. Three of those five passed every J criterion; that does not cancel the price failure. On this clean matched subset the criterion counts are V 20/25 and J 21/25, with **0/5 completed all-passes**. V3 requires proposed unit prices within the unchanged inclusive ±20% of hidden historical target units *and* correct proposal arithmetic. Each V and J criterion contributes 10% to a diagnostic partial score, but completed-quote accuracy requires all ten and a persisted `PRICED_REQUIRES_REVIEW` draft. Neither a high partial criterion score nor a judged price narrative is a completed quote.

The [price-variance analysis](blinded-price-variance-results.md) reconstructs the first-call-to-final numerical changes and the diagnosed pricing misses without changing those verdicts.

A subsequent protocol audit found **three development `keller_polygres` search results** that exposed references or excerpts for **two originally reserved confirmation sources**: one result in baseline and two in matched. This does **not** establish that workers observed full target prices. Initial scopes excluded each case's own target, not the global reserved confirmation set, so the original 30 cannot be called an untouched independent holdout despite zero confirmation RFQs having run. The frozen files were preserved and the two exposed cases quarantined in a separate status record. **Confirmation is blocked** until replacements are selected and new versioned scopes globally exclude reserved sources from every route, including automatic quote analogs. No clean replacement set has yet been frozen; the 28/30 gate does not authorize reuse of the compromised set.

## What changed, and what remains unproven

The baseline ran at `efc888f` with uncommitted scoped-client inputs identified by recorded working-tree file hashes; **the baseline grader itself was not pinned in that version manifest**. The matched version was `5bfdf60b2452d33488210b448892b37d78ef65a1`. Actionable 50-row pagination for prices and search plus a reviewed instruction addressed retrieval limits. After a coordinator environment omission, a documented launcher and real business-tool preflight addressed the startup failure. Inode-based audit/scope alias rejection addressed the route by which one worker misdirected an audit. The original altered scope and extra audit were preserved, the exact original scope was restored by raw SHA-256, and all 180 case-file hashes were checked. **That invalid attempt did not become a pass.**

The latest remediation at `2d6610def086ee6a85e44df6de7f18f9869b53d1` has local verification, but **these worker attempts did not score that remediation**. A manufacturing projection audit supports rejecting material, thickness and process mismatches during triage; it does not establish finished geometry, revision linkage, current process cost or improved pricing accuracy. A bounded drawing audit of 21 non-quote searches and an existing local inventory found no finished geometry tied to the exact requested revisions. A read-only remote follow-up received and parsed one CAD shortcut pointing to a separate engineering share. That locator is not CAD content or evidence of the exact requested revisions. The available file-browser interaction did not successfully issue a direct share lookup, and local remote-desktop rendering prevented an alternative verified lookup. **Remote absence is not established**; broader unpaged corpus and remote locations remain unexamined. Missing geometry has not been established as the sole cause of the pricing misses.

These 18 attempts are a separate population from the [prior 24 exact-reissue attempts](mcp-workflow-evaluation-results.md) and the independent 9/50 historical-prediction diagnostic. Repeated cases and invalid attempts must not be pooled into either accuracy result.

Local checks passed: **86 TypeScript tests, 97 Python tests, 39 script tests, 11 synthetic order scenarios, and plugin typecheck**. Hosted verification and database jobs did not start because of a GitHub billing/spending restriction. The PR remains **draft and unmerged**.
