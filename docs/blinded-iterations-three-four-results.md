# Development iterations three and four: scoped retrieval recovery, not a priced quote

The PR #21 scope-filtering change recovered backend quoting on the five runnable development cases: v4 had **five successful quote calls and no quote-call denials**, versus three denials among six v3 calls. It did **not** complete quoting: **0/5 scored cases and 0/6 preselected cases passed all ten criteria in either iteration, and no final price was adopted**. The recovered numbers are offline tool proposals, not approved customer prices or evidence of improved paired numerical accuracy.

This is an operator-only public-safe summary. Do not add its outcomes, targets or learning provenance to worker-readable guidance. The accompanying private evidence bundle is the place for manifests, requests/oracles/scopes, complete audits, persisted outputs, unchanged grades and judgments, recent-only session captures, numerical and trajectory reports, source-sufficiency corrections and learning provenance; this summary does not reproduce customer details or raw target and quoted dollar prices.

## Controlled setup and coverage

V3 ran executable commit `a85d5b91419d974116b5585a51c0225995ba2b2f` (main after context, build and date-guard fixes); v4 ran `0b9dc19449073be203849b0306774c6fb19f4eb2` (PR #21 pre-estimation scope filtering). V3 and v4 used identical raw request, scope and oracle bytes, the same worker/judge rubric and unchanged V1–V5/J1–J5 thresholds and weights. Luna-max/fast workers used offline backend quote estimation without hosted Jev. Complete scoped MCP audits and persisted drafts were sealed before two independent Luna-max judges in each iteration. The shared-account boundary is application/instructional, not OS isolation; native session snapshots expose only recent visible messages, not complete reasoning or history.

The same five cases were runnable in both iterations. The sixth preselected case, `development-b02-q2`, remained in the selection denominator but was **never launched or graded**: printed/metadata dates conflicted with its original request date at target-chronology preflight. Its criterion flags are unavailable, not ten failures; no easier case replaced it. The v2 scopes differ after the later chronology audit, so v2 comparisons below are descriptive, while the v3/v4 request/scope/oracle basis is matched. These are development snapshot reruns, not untouched confirmation, original-issuance backtests, causal estimates or general accuracy results. Date consistency alone does not prove original issuance, and no impossible issuance-proof gate was imposed.

## Criterion accounting and every transition

| Criterion | V3 passes / 5 | V4 passes / 5 | What passing does and does not mean |
| --- | ---: | ---: | --- |
| V1: trace and final artifact | 3 | 5 | Formerly denied cases regained usable drafts. |
| V2: request identity | 3 | 5 | The recovered drafts preserved their request identity. |
| V3: numerical target and arithmetic | 0 | 1 | One tool proposal met this criterion; none was adopted. |
| V4: internal artifact and review state | 3 | 5 | Complete review-pending artifacts are not released prices. |
| V5: evidence and decision consistency | 0 | 0 | No complete, consistent adopted pricing decision. |
| J1: RFQ intake and interpretation | 5 | 5 | Judges accepted the intake, not quote completion. |
| J2: evidence treatment | 5 | 5 | Honest treatment is not adequate pricing evidence. |
| J3: derivation and hold | 5 | 5 | A defensible hold is not a priced quote. |
| J4: internal handoff | 4 | 5 | The one v3 failure omitted requested line/scope, charges and pricing basis. |
| J5: customer-safe priced draft | 0 | 0 | Customer drafts had no proposed price; appropriately pending terms were not judged guarantees. |

The matched five-case totals are **33/50 → 28/50 → 36/50** for v2 → v3 → v4. The original v2 six-case result remains **40/60**; it is not the matched denominator. Every criterion change in either transition is shown below; “none” means no changed flags in that leg, not that the attempt passed all criteria.

| Case | V2 → V3 → V4 | V2 → V3 gains | V2 → V3 losses | V3 → V4 gains | V3 → V4 losses |
| --- | ---: | --- | --- | --- | --- |
| `development-b01-q1` | 7 → 3 → 7 | None | V1, V2, V4, J4 | V1, V2, V4, J4 | None |
| `development-b01-q2` | 7 → 7 → 7 | None | None | None | None |
| `development-b03-q1` | 4 → 7 → 7 | V1, V2, V4 | None | None | None |
| `development-b03-q2` | 8 → 4 → 8 | None | V1, V2, V3, V4 | V1, V2, V3, V4 | None |
| `development-b03-q3` | 7 → 7 → 7 | None | None | None | None |

V2 → v3 had three gains and eight losses; v3 → v4 had eight gains and zero losses. The recovery does not erase v3's regressions, nor does the descriptive v2 comparison isolate the PR #21 change because its scopes differ.

## Quote-call failures, repair and numerical diagnostics

In v3, full-corpus backend estimation selected ineligible analogs; the response guard then correctly withheld the payload. Exact requests and persisted backend artifacts reconstruct all three denials (`development-b01-q1` audit ordinal 12; `development-b03-q2` ordinals 26–27). They left null final drafts and directly explain those cases' V1/V2/V4 losses; the earlier V3 pass for `development-b03-q2` also became ungradable/failed. The `development-b01-q1` J4 loss had a separate handoff cause: omitted line/scope, charges and pricing basis. No scope leak was proved or delivered. A distinct source-search transient for `development-b03-q3` at ordinal 17 recovered at 18; its exact cause is unknown and is not attributed to the pricing defect.

PR #21 binds a trusted scope **before** retrieval and pricing, reconciles selected rows to the immutable verified export, persists the scoped CSV, and requires matching scope/hash/count proofs on result and review while retaining the response guard. V4's five quote calls succeeded with zero denials; exact eligible rows and UUID-bound persisted outputs were independently reconciled. Formerly denied cases yielded usable internal drafts. This proves observed backend recovery on this development batch, not adoption or customer-ready accuracy.

| First-proposal cohort | Numeric cases | MAPE | Median APE | Signed bias | Signed-error population variance | Standard deviation | Within ±20% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| V3 tool proposals | 3 | 55.47% | 43.68% | +6.89% | 3789.30 pp² | 61.56 pp | 0/3 |
| V4 tool proposals | 5 | 52.70% | 43.68% | −11.93% | 3746.91 pp² | 61.21 pp | 1/5 |
| Final adopted prices, either iteration | 0 | Undefined | Undefined | Undefined | Undefined | Undefined | No completed priced attempts |

V3 had six quote-call rows and three numeric proposals; v4 had five calls and five numeric proposals. Neither had within-case numeric revisions. Population variance divides by `n`, not `n−1`, and is measured in squared percentage points of signed error. Missing/held prices are not numeric zeros. The apparent n=3-to-n=5 MAPE change is **not** an accuracy improvement: the same three cases with numbers in both iterations have identical initial prices and targets, with all paired APE changes zero. Their paired MAPE remains **55.47%** and signed-error variance **3789.30 pp²**.

| Anonymous case | V4 first-proposal signed percentage error |
| --- | ---: |
| `development-b01-q1` | −88.69% |
| `development-b01-q2` | +93.54% |
| `development-b03-q1` | −43.68% |
| `development-b03-q2` | +8.37% |
| `development-b03-q3` | −29.20% |
| `development-b02-q2` | No proposal; preflight-blocked |

All five v4 drafts were `PRICED_REQUIRES_REVIEW`, with `pricing_decisions` holding every line and leaving its proposed price null, review pending and no customer release. V5 failed for the absent complete, consistent adopted pricing decision, and J5 for the absent proposed customer price—not because pending terms were guarantees. One v3 case also had unobserved/ineligible citation tuples; those citation errors were absent in v4, but V5 still failed. J1/J2/J3 passes endorse honest intake, evidence interpretation and hold, not an adequate priced quote.

## Supported numerical diagnosis and limits

An operator replay after sealing, using exact requests, scoped CSVs and source, reproduced **all five serialized line payloads**, not only their prices. Each call used automatic historical mode, retrieved 12 candidates and priced three non-exact candidates, with no exact-part candidate. The offline screen admits score ≥0.3; ranking uses text overlap/fuzzy or prefix part numbers/customer and material bonuses. `median_won` is a weighted median over interpolated quantity curves: its name does not establish verified wins or manufacturing equivalence. `development-b03-q1` requested a quantity outside all usable analog ranges. There were no agent-authored current-cost or explicit-price overrides and no model price revisions. Four-decimal rounding has a worst per-case error bound below 0.0014 percentage points, so it cannot explain the observed misses.

An independent source-sufficiency audit reconciled document counts in all six scopes. It found no exact-part groups; textual candidate hits do not prove geometry or process equivalence. The source search has a **50-per-page limit with pagination**, not a hard 50-result cap. RFQ notes may contain material/finish even without dedicated fields, so neither absent specification content nor inaccessible records after the first page can be inferred. Actual target-price derivations were unavailable: these observations support an analog-sufficiency concern, not a specific cost-cause diagnosis or a global multiplier fitted to private targets.

## Learning, verification and next intervention

One independently accepted v3 preflight snippet (at most 300 characters) was applied verbatim before v4 to test excluded top analogs and persisted eligible rows. That is operational verification guidance, not a demonstrated pricing gain. A separate v4 learning was accepted by exactly one independent reviewer, independently checked against its evidence and existing guidance, and added verbatim to the operator-only [trajectory analysis](mcp-trajectory-analysis.md), not worker skills. It has not demonstrated a behavioral accuracy gain; no targets or results were given to live workers.

At the PR #21 code head, local clean-build validation passed **98 TypeScript, 128 Python and 46 script tests (272 total)**, all 11 synthetic scenarios, source/test/evaluation and runtime-plugin typechecks. A separate live operator preflight passed all five cases, followed by scored v4 runs whose five quote calls passed scope proof. Hosted GitHub database/verify jobs did not start because of the existing billing restriction; this is neither a code test pass nor failure and is not the delivery gate. PR #21 remains open and unmerged without separate user authorization.

The next intervention is better evidence of geometry/process equivalence or supported current costing, tested with frozen blind boundaries and unchanged grades. Repeating identical requests, relaxing criteria or inventing adopted prices would not resolve the observed evidence gap.
