# Observed-price diagnostic (operator only)

This compares **matched, nonempty schema-version-2 EvalReports**, not arbitrary price lists or a commercial-success oracle. It performs no estimation, model calls, source retrieval, or release. Never give its reports, targets, or review sidecars to quote workers, tools, skills, or knowledge stores.

## Invocation and matching

Use the existing local runner; no dependency installation is needed:

```sh
./estimator/node_modules/.bin/tsx evals/observed-price.ts \
  /private/baseline.json /private/candidate.json \
  --mode code-change --private-report /private/diagnostics/new-comparison.json
```

The output parent must already exist, be owner-private (for example mode 0700), and be outside every Git worktree/repository. The output must be a normalized absolute `.json` path. Creation is exclusive, mode 0600; existing files, hardlinks, symlinks, and symlinked parents are refused. Choose a new output name each time. The CLI prints only counts and aggregate relative errors: no paths, IDs, hashes, dollar amounts, or reviewer text. Errors are redacted, including errors originating in the legacy reader. Private details include both full case results and dollar exposure. Protect even aggregates according to the intended audience; small cohorts are not anonymization.

Both modes validate each report with the existing reader (criteria, target provenance, summary, slices and arithmetic), then require the same evalset hash, ordered cases, targets/amounts, quantity, source identity/date, frozen selection slices and effective configuration. Report bytes are hashed for sidecar binding. Derived analog/confidence slices may differ.

* `--mode code-change`: also requires the same register SHA256; source/lock digests may differ.
* `--mode source-basis`: also requires the same estimator/eval source+lock digest and, when supplied, identical hashed-file manifests. Both register hashes are retained separately. This allows a legitimate archived matched-register experiment; it does not attribute source changes to code. It also permits a same-register control.

Changes to both code and register require separate matched conditions, not bypassing either guard. The existing `compare.ts` CLI/gate and the historical **within ±20%** criterion are unchanged. Its exported `readReport(path): Report` is now import-safe. Other exports are `diagnoseReports(baselinePath, candidatePath, mode, sidecarPath?)`, `caseTargetSha256(result)`, `publicSummary(diagnostic)`, and `writePrivateReport(path, diagnostic)`.

The retained schema-2 report headers and current producer shape were inspected for compatibility; no archived diagnostic or benchmark was executed during implementation. Source/lock hashes authenticate neither business events nor every possible transitive dependency. Before a new study, ensure the producer's `hashed_files` covers all exercised changed code and the lockfile. Digest equality and report consistency are not independent authentication of source bytes, historical availability, or a true as-of backtest. An exposed retained cohort remains a development diagnostic, not a fresh blind holdout.

## Denominators and interpretation

Every attempted case remains in `summary.all_cases`. Each condition reports numeric pricing, holds (`no_analog` and `unreplayable` separately), all-pass, and error-eligible counts. Newly priced, newly held, held-both, and the priced intersection are explicit. Invalid/unavailable positive targets have no error metric; they are not erased from coverage. All-unpriced distributions are `null`, not zero.

Error distributions are reported both per condition and on the **same priced intersection**: mean/median APE, nearest-rank p90 APE, mean signed relative error, and under/equal/over counts. Ratios are fractions, not percentages. Signed error is `(proposed - observed) / observed`; APE is its absolute value. Private dollar statistics use full-line extension differences, with their own eligible count: signed total, separate positive/negative exposure magnitudes, absolute exposure, and mean signed unit dollars. Exposure is diagnostic disagreement, not realized loss/profit. An extension can fail its criterion while still yielding a finite diagnostic dollar difference. Criterion and all-pass transitions partition **all cases**, not just priced ones.

No metric says “better,” applies a margin floor, chooses an objective, or declares joint commercial success. Cheaper may mean underquoting; lower median APE may coexist with more holds or criterion losses. No population reliability, current price, future actual-cost, or profit guarantee follows. Customer release still requires named human approval.

## Optional independently reviewed sidecar

Pass `--sidecar /private/review.json`. The generic `ReviewedSidecar` / `ReviewedCase` interfaces in `evals/observed-price.ts` deliberately do not import any cost worksheet. An independent reviewer can adapt a supported worksheet or other evidence into this contract; payment, an accepted order, and closed-job actual costs are not prerequisites for a prospective reviewed estimated range.

Top-level fields (unknown fields are refused):

* `schema_version: 1`.
* `binding: { baseline_report_sha256, candidate_report_sha256 }`: lowercase SHA256 of the **exact report file bytes**, in their named roles. These transitively bind both registers, code/configuration, predictions and targets. Reformatting a report requires a new sidecar binding.
* `cases`: optional coverage of selected cases only; duplicate or foreign IDs fail. Missing cases remain unknown in the all-case denominator.

Each case requires:

* `id` and `target_sha256`, the latter computed by `caseTargetSha256(readReport(path).results[index])`. This stable sorted-key digest binds ID, amount, quantity, source identity/date, document/transcript provenance and frozen selection slices, not predictions or analog/confidence slices.
* `review: { reviewer, authors, reviewed_at, evidence_sha256 }`: nonblank trimmed reviewer/author identities, a nonempty author list, canonical UTC ISO timestamp (including milliseconds), and nonempty evidence hashes. Include **all proposal and cost authors**; the reviewer must differ from them (case-insensitive). This structural independence check cannot detect aliases or authenticate people.
* `stage`: `recorded`, `authenticated-issued`, or `billed`, plus nonempty `stage_evidence_sha256`. Output always calls this `stage_claim`. Recorded historical amounts are not proof of issuance; issuance requires send/version evidence; billed evidence needs invoice/credit and line linkage and is not settlement. A stage label cannot replace the frozen target with a different invoice price. The reviewer must establish the claimed linkage to that same observed amount and scope.
* `comparability`: **every** key in `COMPARABILITY` (`scope`, `quantity`, `uom`, `revision`, `material`, `finish`, `delivery`, `terms`, `charges`, `date`) has exactly `match`, `mismatch`, or `unknown`. Scope includes customer/part identity, drawing, geometry, tolerances and process requirements. Explicit conflict wins over unknown; only all-match permits comparable-price/margin calculations. Not applicable must be supported as match, not silently omitted.

Optional case fields:

* `normalization: { currency: "USD", observed_adjustment, baseline_adjustment, candidate_adjustment, evidence_sha256 }`. All three adjustments are signed finite **full-line dollars** added to the corresponding report's extension. Explicit supported zeros are allowed; omission is unknown. The review must support quantity/UOM, one-off charges, freight, tax exclusions, delivery, date and terms; this is not an automatic conversion engine. Other currencies require an independently normalized diagnostic, not implicit conversion.
* `estimated_cost: { baseline, candidate }`. Each condition is either `{ status: "unknown" }`, `{ status: "unsupported" }`, or `{ status: "reviewed-estimate", low, high, complete, evidence_sha256 }`. Low/high are finite nonnegative **total net cost dollars** on the same normalized scope, with `low <= high`. Nonempty support hashes are required. `complete: true` asserts coverage of material/yield/scrap, setup, labor/machine/routing, outside services and applicable overhead/other allocations; missing costs are not zero. Explicitly approved historical ranges/engineering assumptions can support this estimate, without asserting current actual costs. Incomplete, missing, or unsupported cost yields unknown margin.

The CLI validates hash syntax, exact report/case bindings, states and arithmetic inputs. It does **not** open evidence files or authenticate their contents, reviewer identities, issuance, billing or cost support. Keep independently verified source locators/bytes in the private review record behind the hashes. Every sidecar value is a reviewer claim, not automatically an authenticated fact.

With all-match comparability, explicit normalization and a positive reconciled proposal/observed net total, the private report computes signed comparable-price dollar and relative differences. With complete supported estimated costs it additionally computes margin `[ (revenue - high_cost) / revenue, (revenue - low_cost) / revenue ]`. Unknown normalization or scope, held/unreconciled prices, or nonpositive net totals produce `null`; no cost is silently substituted. Supported margin and comparable-price availability, their unknown complements, comparability verdicts and stage claims have separate counts. There is no joint-success numerator. Any future approved competitiveness/margin policy must be frozen independently before evaluation, not inferred from target prices.

## Verification handoff

Synthetic tests live in `estimator/test/observed-price.test.ts`: matching failures, unchanged legacy gate/20% boundary, signed versus absolute errors, held/invalid denominators, independently bound review claims, scope conflicts, unsupported/incomplete margins, output permissions/aliases/Git refusal, import safety and redacted CLI output. They were written but **not executed** during implementation; no tests, builds, benchmarks, installations or external calls were run. Parent integration should run them and the existing evaluation suite after PR creation, then perform any separately authorized offline matched diagnostic with new private outputs. Do not treat an archived run as a current-code baseline.
