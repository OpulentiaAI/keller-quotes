# Operator-only pricing evaluation and historical results

This guide is for operators preparing private target sets, running experiments and interpreting historical results. It is **not** a worker-readable contract or a permitted `read_file_pinned` path in blinded scopes. Use the [worker-safe source, quote and order contract](pricing-evals-and-orders.md) for source basis, quote-time cutoff, exact arithmetic and human release safeguards. Keep real customer PDFs/transcripts, registers, requests and reports in approved private storage outside the checkout. Audit every worker-readable context channel before launching a blind evaluation, including pinned files, canonical skills, tool descriptors, prompt text and any injected or retrieved content; guard permission alone does not make a file blind-safe.

## Matched historical replay

The fixed 250-case `evals/evalset.jsonl` targets internal `QUOTQTYS` prices. Do not regenerate or overwrite it to make a score better. To measure against issued customer prices, create a separate private v2 target file from the validated document CSV; the generator selects one break per part family using deterministic salted SHA ranks independent of register row order, and writes a manifest with CSV/selection digests. It validates provenance field format and price arithmetic, but **does not reopen PDF/transcript files or independently recompute their hashes**; upstream verification and private source review remain necessary. The evaluation itself can SHA-sample the same case IDs independent of JSONL order. From repository root after `(cd estimator && npm ci)`, export the explicitly selected corpus read-only and run:

```sh
python scripts/document-evidence-db.py export --expected-database "$DB_NAME" \
  --corpus "$CORPUS_ID" --out "$VERIFIED_CSV"
python scripts/generate-document-eval.py "$VERIFIED_CSV" \
  "$NEW_PRIVATE_CASES.jsonl" --count 250
node estimator/node_modules/tsx/dist/cli.mjs evals/run-eval.ts \
  "$NEW_PRIVATE_CASES.jsonl" --register "$VERIFIED_CSV" \
  --sample 50 --seed keller-eval-50-v1 --report "$NEW_PRIVATE_VERIFIED_REPORT.md"
node estimator/node_modules/tsx/dist/cli.mjs evals/run-eval.ts \
  "$NEW_PRIVATE_CASES.jsonl" --register quotes.csv \
  --sample 50 --seed keller-eval-50-v1 --report "$NEW_PRIVATE_INTERNAL_REPORT.md"
```

The export validates complete original CSV fields and digest. Both runs use **the same document targets**, but different registers, so the delta is a **data-source** comparison, not proof of a code gain. `--limit 50` is a prefix, not the SHA sample, and cannot be combined with `--sample`; pin case IDs, source register/evalset/source+lock digests, seed and mode. The harness excludes the source `quote_no` across all its breaks. For each case, it restricts other quote/letter/revision events and visible outcomes to before the target's verified letter date. A missing identity/date makes a case unreplayable. The snapshot cannot rule out later unversioned edits in older rows, so quote-time replay is not a true historical backtest. The fixed legacy set is won/recent-biased; the document sample is deterministic, not a representative prospective holdout. `--retrospective` admits future information; `--jev` requires a gateway key and may fall back even when configured. Neither is the default offline experiment.

The v2 private JSON report contains per-case target PDF/transcript hashes, source field/full price/extension, analog basis and available quote/letter/last-touch dates and revisions, selection/configuration hashes, cutoff/exclusion criteria and slices. Audit those before reading aggregate prices. Missing source metadata cannot be verified by the grader. Report `cases`, `priced`, `no_analog`, `unreplayable`, and coverage as priced / all. Median APE and within-±20% are **priced-only**; all-pass is **all cases**, so holding a line cannot inflate readiness. Show failed cases and signed extended-dollar error on priced pairs; this is not order-level success. Confidence and price bands are diagnostics, not calibrated customer release thresholds. No independent proof says Jev, a recency multiplier, or an exact-part heuristic helps; run a matched comparison rather than assuming it.

For a code-only change with **identical register bytes, target file, case selection, actuals and configuration**, run the two reports and compare their JSON sidecars:

```sh
node estimator/node_modules/tsx/dist/cli.mjs evals/compare.ts \
  "$BASELINE_JSON" "$CANDIDATE_JSON" \
  --report "$NEW_PRIVATE_COMPARISON.md" --fail-on-regression
```

`compare.ts` rejects differing register/target/selection/configuration; source-code digests may differ. Its regression flag catches lower coverage, higher median APE or lower all-pass, but is an engineering diagnostic, not a statistically validated business approval threshold. For the two-register document experiment, compare the matched reports and exposed basis counts manually; do not bypass the incompatibility check. Never compare the original 250 internal targets to the new document targets as though accuracy improved.

The final matched 50-case document-price experiment (2026-09-28) priced 48/50 in both register conditions. Against the **same PDF targets**, the internal register had median APE 75.5361%, within ±20% on 18.75% of priced cases, all-pass 9/50; the verified register had median APE 63.3716%, within ±20% on 16.6667% of priced cases, all-pass 8/50. The verified run exposed 234/234 analog refs with verified basis and held two no-analog lines; neither run exposed source/cutoff leaks. The lower median came with **worse** within-20 and all-pass, so it is not a blanket accuracy gain or an autonomous pricing release. The source+lock SHA-256 was `e52bfce6b646af8ac0066a8d1552fb71a27e44eb717b186ac59cb710638c92e4` and the selected document case IDs SHA-256 was `bd1b94393891fca2328e80aaaeb1f325381231c99f3c0c2ff006203027e2c4d2`. This was an offline harness run directed by Codex GPT-6 Sol (medium), **not** model-generated pricing. A retrospective future-visible score would answer a different question. The separate fixed legacy 250-case eval has internal targets and cannot be numerically compared with this PDF-target experiment.

The [exact-part and quantity-weighting experiment](pricing-optimization.md) reports aggregate gains alongside a diagnostic holdout within-20% regression and supplemental signed-dollar underquoting. Those observed historical results predate the combined admission pipeline and are not evidence that the combined policy improves pricing accuracy; do not tune against them as fresh blind targets.

## Separate synthetic order-workflow benchmark

```sh
node estimator/node_modules/tsx/dist/cli.mjs evals/run-orders.ts \
  --tasks evals/tasks --out "$NEW_PRIVATE_BENCHMARK_DIRECTORY"
```

Each synthetic task supplies only its request/register to the solver. A separate grader reloads persisted JSON/Markdown and scores required arithmetic, line completeness, blockers, readiness and provenance criteria; all required criteria must pass. `scores.json` and `report.md` distinguish fully priced, correctly blocked and correctly rejected invalid requests. A correct refusal is a **safety pass**, not a priced order; a formatted order does not prove its historical price is right. `node scripts/verify.mjs` covers test/typecheck/build and synthetic order/eval checks. Keep private real artifacts outside the checkout and avoid committing reports with customer identities. This all-pass pattern borrows task-local deliverable grading from [Harvey Labs](https://github.com/OpulentiaAI/harvey-labs/blob/845a08840869b21a5c11958aae58bf5f00a7b775/docs/eval-strategies.md), without importing its legal-task data or LLM judge.
