# Steve development diagnostic — 2026-10-09

**Operator-only evaluation findings. Not worker context, untouched confirmation, or evidence of >90% end-to-end accuracy.** Private targets, customer identifiers, amounts and case-level reports are excluded from this document.

## Frozen design

All 250 previously retained customer-PDF cases were attempted under both source conditions, on baseline `34a0880037cf1cd40ae062e68b7201ad0b8c4cd9` and implementation `169176ce` (full implementation identity is also bound by the source digest below). No cases were dropped, sampled or replaced. Four runs exited successfully. Jev was disabled; the target quote was excluded and the metadata cutoff was strictly before the case date. The unchanged criteria were finite positive price, target exclusion, metadata cutoff, unit error within 20%, and extension reconciliation. This is a historical frozen-snapshot diagnostic, not a true availability backtest.

The same cases were used in both source conditions. Their targets are recorded customer-PDF prices, never internal targets. Comparing source conditions is a source-basis experiment, not a code improvement. None of these runs tests PDF interpretation, live supplier buying prices, engineering/routing completeness, supported margin or actual job profitability.

## Paired results

APE and signed errors below are conditional on priced cases; all-pass always divides by all 250 attempts. Positive signed error means overquotation relative to the recorded target.

| Metric | PDF baseline | PDF candidate | Internal baseline | Internal candidate |
|---|---:|---:|---:|---:|
| Priced / all | 220/250 | 220/250 | 244/250 | 244/250 |
| Held / all | 30/250 | 30/250 | 6/250 | 6/250 |
| All-pass / all | 45/250 (18.0%) | 45/250 (18.0%) | 46/250 (18.4%) | 47/250 (18.8%) |
| Median APE | 55.9602% | 56.1592% | 61.8640% | 59.5996% |
| Mean APE | 109.1671% | 103.0389% | 99.7321% | 102.1681% |
| P90 APE | 175.1941% | 165.0796% | 163.0165% | 194.4802% |
| Mean signed relative error | +53.6080% | +46.0588% | +29.1161% | +35.4879% |
| Under / over target | 129 / 91 | 128 / 92 | 158 / 86 | 152 / 92 |

- PDF code comparison: 3 gained all-pass, 3 lost, 42 passed both, 202 failed both. No newly priced or newly held cases. **The existing `compare.ts --fail-on-regression` check exits 1 because median APE worsened.** Do not call the lower mean/tail an unqualified improvement.
- Internal code comparison: 4 gained, 3 lost, 43 passed both, 200 failed both. No coverage change. The existing aggregate check exits 0, but mean and P90 error worsen; that check does not make the policy commercially acceptable.
- Candidate source-basis comparison: 220 priced in both, 24 priced only on internal history, 6 held in both. PDF gained 23 all-pass and lost 25 relative to internal history, with 22 passing both. On the 220-case priced intersection, median APE is 58.9676% internal versus 56.1592% PDF; all-case completion remains lower for PDF. No source is universally superior.
- Source-exclusion and metadata-cutoff checks pass on all 250 in each run. Those mechanical checks do not authenticate historical document availability. Extension checks pass on priced cases and fail on holds.

## Failure investigation

All 220 PDF-priced cases were classified as `other analog`, not exact part. Of the internal-source cases, only 5 used an exact-part analog (1 passed); 239 used other analogs (46 passed), and 6 held. This is observed retrieval classification, not proof of manufacturing equivalence or its absence.

All six PDF all-pass transitions changed their exposed contributor set while retaining the `median_won` strategy; 25 PDF predictions changed overall. All seven internal transitions changed contributor sets; five retained `median_won`, two changed from `latest` to `median_won`; 40 predictions changed overall. These are diagnostics, not causal proof that a particular screening rule improved accuracy. No target-derived policy adjustment was made after viewing these results.

The concrete bottleneck is still support for manufacturing equivalence and bottom-up cost, not producing more historical analog numbers. The implementation now retains compatibility conflicts/unknowns, bounded source access, operator evidence and deterministic supplied-cost worksheets. It does not extract and independently verify complete routing and purchasable current inputs automatically.

No independent commercial sidecar was supplied: comparability, lifecycle stage and supported estimated margin remain unknown for all 250 cases, retained in the denominator. Recorded targets alone do not authenticate issuance or billing. No realized-margin or better-price claim is supported. A future engineering/cost policy must be developed on disclosed development cases and evaluated on a separately frozen, isolated confirmation cohort with independently reviewed scope and cost truth; do not reuse this cohort as fresh confirmation.

## Reproducibility identities

| Artifact | SHA-256 |
|---|---|
| Pre-run plan | `7199501d8dfc75ac7072a458a474f8923cbb36c398f44b6c99af6059ffec10a3` |
| Frozen cases | `12414d36a0f2d721d86d74dea61a66673c043931668f7573ece4f27553445311` |
| Selected case IDs | `2acbbe76ec4b08e33ccfaf9e48b040c42d4448c0f2c2f72e870d571f1351b38a` |
| PDF register | `a7d84545b00ecb3f976d100d3e214885cca009189c1f59c500687539e5728757` |
| Internal register | `6ed19d0cf550f3e65f420b676bbc4354c8dfaf05912d1f5f4edefb4bc8b24cfe` |
| Baseline source + lock | `38b1f10288288a39d6e0dd08d979dbc87e906060598104c48356ed347c5a32fe` |
| Candidate source + lock | `3012952b7d11fc0bcf47ddd4646c241a5a4aeba4fcfbcfc90dd9cdc941ec9476` |

The candidate source manifest adds `estimator/src/evidence.ts`; unchanged grading code and configuration remain pinned. Private execution records retain all four full reports, stdout/stderr, signed-dollar errors, matched comparisons, diagnostics and transition details. Do not place those private artifacts into worker context.

## Software verification, separate from pricing performance

The canonical verifier passed: 192 estimator tests, TypeScript build, estimator/evaluation typechecks, 202 Python tests, 56 script tests, compiled offline CLI smoke, and 11 synthetic order tasks (7 completed orders, 2 correct holds, 2 correct validation rejections). Synthetic completion is not observed-price accuracy.

Execution history is preserved: the first full run found an instruction-contract omission (fixed) and a pre-existing Git proxy rewrite affecting the synthetic runtime fixture. A concurrent isolated run hit the existing five-second test timeout; no timeout or assertion was relaxed. A final serialized run passed with process-local `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1` and synthetic author identity. No global Git settings were modified. No repository lint command is configured; TypeScript checks and `git diff --check` passed. Live mailbox, hosted Jev, database mutation, customer sending and production scheduler activation were not exercised or enabled.
