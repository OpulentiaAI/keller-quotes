---
name: keller-estimator-evals
description: Evaluate Keller pricing replay against frozen internal calculations or privately generated verified customer-PDF targets, with matched-case provenance, coverage, and separate synthetic order checks.
---

# Evaluate pricing evidence and workflow separately

An accurate historical target, an accurate estimate, and a complete order are different claims. The fixed `evals/evalset.jsonl` has 250 **internal-calculation** targets from `quotes.csv`; never replace it with customer-price targets. The document-verified target set must be versioned separately and kept private. Historical replay excludes the source quote number across all its breaks and uses an exclusive quote-date cutoff for other quotes, letters, and known revisions/outcomes. The PDF set's recorded date derives from reconciled inquiry/header metadata, not a reconstructed original `QUOTEN` date or independently proved PDF-version availability. Reconcile printed footer dates before relying on a source's prior availability; unresolved chronology blocks that claim. Earlier snapshot rows may contain unversioned later edits: this is metadata-cutoff **frozen-snapshot replay**, not a true backtest or production prevalence estimate. See [the source and order contract](../../../docs/pricing-evals-and-orders.md) for order requirements and [document evidence](../../../docs/document-evidence.md) for source provenance.

Ars Umbris `keller_quote` builds reviewed internal order drafts and `keller_sources` exposes bounded private evidence reads; neither runs this evaluation suite or establishes the ≥90% completed-quoting goal. Run the offline evaluation commands below in an approved private operator environment, retaining separate target, coverage, and blocker accounting.

## Adjudicate evidence and completed decisions before interpreting scores

Run `python -B scripts/keller-ground-truth.py assess --config "$PRIVATE_ASSESSMENT_CONFIG"` when auditing target meaning or source fitness. Follow [the executable assessment contract](../../../docs/ground-truth-assessment.md): supply the frozen full evalset, all-case bindings, original physical references/document proofs, source manifest, unchanged candidate report and explicit original-byte paths. It verifies actual hashes/identities/quantities/full-price arithmetic and produces a versioned private all-case assessment plus at most ten case-linked remediation tasks. Missing selected PDF coverage is not a false internal target; later/different letters and revisions stay separate. `UNIT_SELL`, posted won history, source mtime and agent narrative cannot establish acceptance, actual cost, current quote support or optimum.

For completed quotes, use the **separate** `python -B scripts/keller-ground-truth.py decisions --config "$PRIVATE_DECISION_CONFIG"`, not replay all-pass or the synthetic order score. Freeze full RFQ eligibility, every line/specification/UOM/quantity/revision and terms, independent source-bound assessment and worker-visible source hashes before actual attempts. Retain all actual attempts and raw trace/draft/price-decision hashes, plus named independent source review, its execution receipt and human handoff. Every required criterion must pass; a finite numeric provisional amount without current manufacturing/cost support is not completed success. Held/errors/timeouts/invalid/missing/dropped attempts remain failures in the eligible denominator. Correct predeclared blocked cases have a separate safety score and never lift completion.

Keep these assessments, sources, targets and review packets operator-only outside Git and blinded scopes. The executable reports an observed rate but cannot certify the ≥90% live goal from this exposed diagnostic, synthetic tasks, owner assertions or self-declared live traces. Do not change legacy targets, grades, controller baselines, denominators or ±20% tolerance to resolve a domain mismatch.

## Run reproducible, offline experiments

Before starting a scored MCP batch, use the documented service launcher and verify a real evidence read and draft generation. Successful tool discovery alone does not validate backend dependencies.

For Keller scoped-quote preflight, include a case whose full-corpus top analog is excluded and verify the persisted register contains only eligible rows. A successful quote whose chosen sources happen to be allowed does not establish pre-estimation isolation.

Before launching blinded Keller workers, inspect the actual content delivered by every allowlisted skill and contract, not just its path. Keep historical scores and experiment outcomes in operator-only files, and verify that the scoped client denies those files.

For short **model-driven workflow** evaluations, use fresh Luna-max worker contexts for three frozen RFQs through `Keller Workflow` standard MCP, then a separate Luna-max judge. Freeze request/oracle/criteria/model/skill hashes, retain every tool response and persisted draft, and preselect a fresh three-question batch before editing skills. Mechanical validation and judging receive equal weight, but their failures cannot cancel each other. See [the workflow evaluation contract](../../../docs/mcp-workflow-evaluations.md) for V1–V5/J1–J5, grader invocation, adversarial calibration and the separate learning-review loop. These tests do not replace the historical replay below.

For **each** workflow iteration, follow [private trajectory analysis](../../../docs/mcp-trajectory-analysis.md): record what actually ran and what transcript/audit coverage exists, seal answers before independent judging, compare every criterion on matched requests, investigate pass-to-fail losses despite aggregate gains, and link retrospective price errors to observed draft ordinals without leaking targets to blinded workers. Preserve invalid attempts; development reruns diagnose, while fresh globally isolated cases confirm. Promote only verified, independently reviewed reusable learnings into scoped guidance.

In Keller workflow analysis, distinguish tool proposals from adopted prices using the final pricing_decisions and draft. A retained PRICED_REQUIRES_REVIEW payload with a null proposed_unit_price is a hold, not a final priced quote.

Require every mechanical validator and independent judge criterion for a completed all-pass. A judge's acceptance of evidence and communication cannot override a failed request-identity check; keep that case in the attempted denominator.

Run from the repository root after `(cd estimator && npm ci)`. Use owner-only private directories outside the checkout for real target sets, PDF-register exports, and reports; create new filenames for every run. Select/export a verified corpus read-only as described by [Polygres](../polygres/SKILL.md). The generator validates the full input CSV's required provenance **field formats**, `customer_quote_pdf` basis, unknown outcome, five-decimal source precision and cent-rounded extension, then selects one break per normalized part family by independent salted SHA ranks. It hashes the CSV and writes a v2 JSONL and manifest, but **does not open PDFs or transcripts or recompute their hashes**: source authenticity/reconciliation depends on the upstream verified export and original review. It does not write to Polygres or the checkout.

```sh
python scripts/generate-document-eval.py "$VERIFIED_CSV" \
  "$NEW_PRIVATE_CASES.jsonl" --count 250
node estimator/node_modules/tsx/dist/cli.mjs evals/run-eval.ts \
  "$NEW_PRIVATE_CASES.jsonl" --register "$VERIFIED_CSV" \
  --sample 50 --seed keller-eval-50-v1 --report "$NEW_PRIVATE_REPORT.md"
```

Use `--register quotes.csv` **explicitly** for a legacy-source experiment on the **same document cases**; do not present that as a code improvement. The old internal 250-case set instead runs with `evals/run-eval.ts evals/evalset.jsonl --register quotes.csv --report "$NEW_PRIVATE_LEGACY_REPORT.md"`. `--sample` SHA-ranks IDs independently of input order; pin its seed explicitly (`--seed` is optional in the CLI). `--limit` selects the physical file prefix and is mutually exclusive with `--sample`. Never compare unlike selection methods. Neither `--jev` nor `--retrospective` belongs in the default offline quote-time run: the former requires a gateway key and can fall back despite being configured, and the latter deliberately exposes future history.

Record the **selected case IDs digest**, evalset/register SHA-256, source+lock digest and effective configuration, and audit private per-case target PDF/transcript/field/full-unit/extension, exposed analog price bases, source-quote exclusion and cutoff verdicts. Missing source identity is `unreplayable`, not a price; `no_analog` is a held case, not a fabricated zero. Report counts for **all cases, priced, no analog, and unreplayable**. Median APE and within ±20% use **priced cases only**; all-pass uses **all cases**, including held failures. If no line is priced, error is `n/a`, not zero. Diagnostic confidence bands and the deterministic grouped split are not calibrated release gates or blind holdouts.

For a code change on the **same** register and exact targets/IDs/configuration, compare both JSON reports:

```sh
node estimator/node_modules/tsx/dist/cli.mjs evals/compare.ts \
  "$BASELINE_REPORT.json" "$CANDIDATE_REPORT.json" \
  --report "$NEW_PRIVATE_COMPARISON.md" --fail-on-regression
```

The comparison rejects incompatible register/case/target/configuration evidence and checks coverage, median error and all-pass regressions, but is not a calibrated business acceptance test. Changing the register is a **data-source experiment**, so compare matching document targets and selected IDs manually across report summaries and basis audits; `compare.ts` correctly rejects the different register digest. Comparing the original 250 internal targets to the new PDF targets is invalid. Inspect per-case failures, diagnose one hypothesis at a time and rerun identical cases; do not assert that recency tweaks, exact-part matching, Jev, or any confidence threshold improves accuracy until a matched experiment demonstrates it. Evaluate median APE, within-20 and all-pass separately; no single metric authorizes unattended pricing.

Treat historical experiments as operator-only evidence, not fresh blind targets or proof of any current pricing policy. Test proposed changes against matched cases with unchanged source basis and an independently isolated confirmation set before claiming improvement.

For independent **synthetic order-workflow** checks, run `node estimator/node_modules/tsx/dist/cli.mjs evals/run-orders.ts --tasks evals/tasks --out "$NEW_PRIVATE_BENCHMARK_DIR"`; these grade persisted JSON/Markdown for arithmetic, completeness, blockers and refusal. `node scripts/verify.mjs` covers repository tests and the synthetic benchmark. Neither measures live market-price accuracy. A correct `BLOCKED` outcome is a safety success, not a completed order. All customer requests, source PDFs, transcripts, generated target sets, and reports remain private outside the repository; never tune against a diagnostic split then call it independent validation.
