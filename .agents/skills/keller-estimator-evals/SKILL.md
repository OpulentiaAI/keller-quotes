---
name: keller-estimator-evals
description: Run leave-one-out evaluations of the Keller quote estimator against its own history, read the metrics, and hill-climb accuracy. Use when tuning the estimator, validating a change to retrieval/pricing, or measuring accuracy.
---

# Keller Estimator Evals

The eval set (`evals/evalset.jsonl`) is sampled from the register itself: each case replays a historical quote line as a fresh pricing request, with the source quote excluded from its own analogs. The default harness also excludes quotes, revisions, and letters on/after the case date, and hides wins not known before then. It scores predicted unit price vs the actual quoted price. This is a cutoff-aware **frozen-snapshot replay**, not a true backtest: earlier rows may contain later unversioned changes. The eval sample intentionally overweights won and recent quotes, so its metrics do not represent natural production prevalence.

## Current baseline (v0, offline deterministic path)

The committed v0 `evals/report-baseline.md` used retrospective leave-one-out and exposed future data: 250 cases · coverage 98.8% · median APE 46.3%. Do not compare that number directly to the cutoff-aware default. Regenerate the report after an estimator change; use `--retrospective` only when explicitly analyzing the old, future-visible behavior.

That is a *starting point*, not a target. Job-shop quotes span 1994–2026 with no inflation normalization, so historical-dollar APE is inherently high; hill-climbing should improve analog selection and staleness handling first.

## Running an eval

From the repo root:

```bash
cd estimator && npm install && cd ..    # first time only

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

## Knobs that move the metric (ranked by expected leverage)

- **Recency weighting** (`recencyWeight` in `src/price.ts`, ~8y decay): too weak → 1990s prices dominate medians. Tightening decay or adding a hard era cutoff is the highest-leverage knob.
- **Same-part-in-another-quote bonus**: `to_quote` lineage and re-quotes of the same part_no are the strongest evidence — retrieval already matches exact part_no at 1.0; consider boosting *recent* exact matches further.
- **Exact-match dominance**: when an exact part_no analog exists, description-similar analogs probably shouldn't anchor the median — gate `curve_fit`/`median_won` to exact matches when present.
- **Screen rejections feeding back**: rejected analogs indicate retrieval noise — check their `reasons` before tuning weights.
- **Jev on/off**: `--jev` changes ranking quality; run both, keep whichever wins on median APE (Jev should win on ambiguous cases).

## Rules

- Never eval without `exclude` — the estimator finding its own source quote is the #1 way to fabricate accuracy.
- Never tune on the eval set to a specific case — optimize metrics, not misses.
- Keep `evalset.jsonl` frozen while comparing two estimator versions; regenerate it only when the register itself changes.
- Record every run's summary in the PR that changed the estimator — metric without provenance is noise.
