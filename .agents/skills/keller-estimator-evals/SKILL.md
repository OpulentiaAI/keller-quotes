---
name: keller-estimator-evals
description: Run leave-one-out evaluations of the Keller quote estimator against its own history, read the metrics, and hill-climb accuracy. Use when tuning the estimator, validating a change to retrieval/pricing, or measuring accuracy.
---

# Keller Estimator Evals

The full workflow is documented in `docs/pricing-evals-and-orders.md`. In addition to historical replay, `evals/run-orders.ts` grades synthetic request-to-order tasks from persisted JSON/Markdown artifacts using deterministic, all-pass rubrics inspired by Harvey Labs. These are workflow correctness checks, not evidence that historical prices are accurate.

The eval set (`evals/evalset.jsonl`) is sampled from the register itself: each case replays a historical quote line as a fresh pricing request, with the source quote excluded from its own analogs. The default harness also excludes quotes, revisions, and letters on/after the case date, and hides wins not known before then. It scores predicted unit price vs the actual quoted price. This is a cutoff-aware **frozen-snapshot replay**, not a true backtest: earlier rows may contain later unversioned changes. The eval sample intentionally overweights won and recent quotes, so its metrics do not represent natural production prevalence.

## Reference baseline (cutoff-aware, offline deterministic path)

The 2026-09-26 replay of the fixed 250-case set on pricing code from `4cc5b23` prices 237 cases (94.8% coverage), with median APE 53.0% and 23.2% of priced cases within ±20%. See `docs/execution.md` for the source digests, exact command, and release gates. This is evidence for a manual-review draft tool, not unattended pricing.

`docs/pricing-optimization.md` records the exact-match/quantity-weighting experiment and its development, diagnostic-holdout, and separate 500-family validation results. It documents the holdout within-20% regression alongside aggregate gains. Do not treat either observed validation set as a fresh blind holdout for further tuning, or assume a stronger recency weight improves accuracy; the tested latest-only and two-year-decay alternatives performed worse.

The committed v0 `evals/report-baseline.md` used retrospective leave-one-out and exposed future data: 250 cases · coverage 98.8% · median APE 46.3%. Do not compare that number directly to the cutoff-aware default. Regenerate the report after an estimator change; use `--retrospective` only when explicitly analyzing the old, future-visible behavior.

That is a *starting point*, not a target. Job-shop quotes span 1994–2026 with no inflation normalization, so historical-dollar APE is inherently high; hill-climbing should improve analog selection and staleness handling first.

## Running an eval

From the repo root:

```bash
cd estimator && npm ci && cd ..    # first time only

# full 250-case run, deterministic (no API key needed)
./estimator/node_modules/.bin/tsx evals/run-eval.ts \
  --register quotes.csv --report evals/report-<label>.md

# subset while iterating
./estimator/node_modules/.bin/tsx evals/run-eval.ts --limit 50 --report /tmp/quick.md

# with Jev ranking (needs AI_GATEWAY_API_KEY)
./estimator/node_modules/.bin/tsx evals/run-eval.ts --jev --report evals/report-jev.md

# old leave-one-out with future data visible (not quote-time accuracy)
./estimator/node_modules/.bin/tsx evals/run-eval.ts --retrospective --report /tmp/retrospective.md
```

Each run writes `report-<label>.md` (metrics table + worst-10 misses) and a `.json` with per-case results for deeper slicing. The summary separately counts unpriced (`no_analog`) and invalid/undated (`unreplayable`) cases; when none is priced, accuracy is `n/a`/`null`, not a fabricated zero.

`--jev` requires `AI_GATEWAY_API_KEY` and fails before writing reports when it is missing. The report now uses `summary.jev_configured` instead of `summary.jev`: a configured client can still fall back if a provider call fails, so this field is not proof that every decision used Jev. Median APE averages the two central values for an even number of priced cases.

Schema-version-2 reports pin register/evalset/source/lockfile digests and record per-case criteria, all-pass rate over all cases, signed errors, and confidence/evidence/era/quantity/outcome slices. The grouped development/holdout partition is diagnostic, not a blind holdout. Compare two compatible reports with `evals/compare.ts baseline.json candidate.json --report out/comparison.md --fail-on-regression`; mismatched data, cases, actuals, quantities, or modes are rejected. Keep the fixed historical set unchanged and distinguish its empirical pricing score from synthetic order-completeness scores.

## Regenerating the eval set

```bash
cd estimator && ./node_modules/.bin/tsx scripts/gen-evalset.ts ../quotes.csv ../evals/evalset.jsonl 250
```

Deterministic seed (42), stratified toward won/recent/multi-break quotes. Change N or the seed only deliberately — keep a fixed set while comparing estimator versions, version-bump the set when the register changes.

## Hill-climb workflow

1. **Establish the baseline** — run the eval, commit the report filename/metrics somewhere durable (this file's baseline section or the PR).
2. **Change one thing** — retrieval weights in `src/retrieve.ts`, interpolation/weighting in `src/price.ts`, candidate limits in `src/estimate.ts`.
3. **Re-run the same evalset** and compare median APE + within-±20% + coverage. Keep changes that move the metric; revert ones that don't.
4. **Inspect the worst misses** in the report — they cluster (usually: era drift, single-analog lines, description-only matches on generic parts). Fix classes, not individual rows.
5. **Sanity-check** that confidence still tracks accuracy (high-confidence lines should be the accurate ones; if a change decouples them, the confidence model needs updating too).

## Policy checks and remaining hypotheses

- **Recency weighting** (`recencyWeight` in `src/price.ts`, ~8y decay): staleness is a risk signal, not proof that stronger decay improves accuracy. The tested two-year decay and latest-only policy worsened development results; do not apply a blanket inflation uplift to quote-time replay.
- **Same-part-in-another-quote bonus**: `to_quote` lineage and re-quotes of the same part_no are the strongest evidence — retrieval already matches exact part_no at 1.0; consider boosting *recent* exact matches further.
- **Exact-match dominance and quantity relevance**: the measured proposal prefers priceable exact matches within the retrieved pool and downweights distant break quantities. Review its documented holdout tradeoff instead of claiming every slice improved.
- **Screen rejections feeding back**: rejected analogs indicate retrieval noise — check their `reasons` before tuning weights.
- **Jev on/off**: compare matched, explicitly authorized runs before claiming a ranking improvement. Configured access does not establish provider success or superior pricing accuracy; no live Jev experiment underpins the offline results.

## Rules

- Never eval without `exclude` — the estimator finding its own source quote is the #1 way to fabricate accuracy.
- Never tune on the eval set to a specific case — optimize metrics, not misses.
- Keep `evalset.jsonl` frozen while comparing two estimator versions; regenerate it only when the register itself changes.
- Record every run's summary in the PR that changed the estimator — metric without provenance is noise.
