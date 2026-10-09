---
name: keller-estimator-evals
description: Operator-only Keller pricing evaluation with matched-case provenance, preserved coverage/holds, distinct commercial claims and separate synthetic order checks.
---

# Evaluate pricing evidence and workflow separately

This is operator evaluation guidance, not permission to expose archives, targets, later outcomes or reports to quote workers. An accurate historical target, an accurate estimate, and a complete reviewed quote are different claims. The fixed `evals/evalset.jsonl` has 250 **internal-calculation** targets from `quotes.csv`; never replace it with customer-price targets. Document-verified targets stay separately versioned and private. Historical replay excludes the source quote number across all breaks and uses an exclusive quote-date cutoff for other quotes, letters and known revisions/outcomes. The PDF set's recorded date derives from reconciled inquiry/header metadata, not independently proved PDF-version availability. Reconcile printed footer dates; unresolved chronology blocks prior-availability claims. Snapshot rows can contain unversioned later edits: this is **frozen-snapshot replay**, not a true backtest or production prevalence estimate. See [the source/order contract](../../../docs/pricing-evals-and-orders.md) and [document provenance](../../../docs/document-evidence.md).

`keller_quote` builds offline internal drafts; `keller_sources` offers authorized operator evidence reads. Neither proves the greater-than-95% all-eligible completed-quoting goal. Predeclare independent RFQ eligibility/denominator, first-attempt/retry policy, sample size and uncertainty interval; preserve held, invalid, failed and timed-out eligible attempts. Numeric coverage, safe holds and completed independently reviewed proposals are separate counts. Payment/closed-job ledgers are not prerequisites for a supported prospective estimate, but are required as appropriate for realized-outcome claims.

Use the [operator-only observed-price diagnostic](../../../docs/observed-price-diagnostic.md) to distinguish **recorded-price agreement**, **supported estimated margin**, **comparable competitiveness**, and **realized outcome**. Match stage, quantity/UOM, revision/material/finish, scope, date, delivery, terms and charges before calling a price competitive. Unknown costs/comparability remain unknown in denominators, never zero or success. Fix margin/competitiveness policies before comparison; a cheaper quote below the approved margin floor is not joint commercial success. No oracle, archive root or diagnostic tool belongs in a blinded worker's skills/tools/knowledge allowlist.

## Run reproducible, offline experiments

Before a scored MCP batch, verify an authorized bounded evidence read and draft generation in the approved configured environment. Discovery alone does not validate the backend. Runtime readiness is only a precondition, not a pricing improvement or permission to start services/change bindings.

For Keller scoped-quote preflight, include a case whose full-corpus top analog is excluded and verify the persisted register contains only eligible rows. A successful quote whose chosen sources happen to be allowed does not establish pre-estimation isolation.

Before launching blinded Keller workers, inspect the actual content delivered by every allowlisted skill and contract, not just its path. Keep historical scores and experiment outcomes in operator-only files, and verify that the scoped client denies those files.

For short **model-driven workflow** evaluations, use fresh Luna-max worker contexts for three frozen RFQs through `Keller Workflow` standard MCP, then a separate Luna-max judge. Freeze request/oracle/criteria/model/skill hashes, retain every tool response and persisted draft, and preselect a fresh three-question batch before editing skills. Mechanical validation and judging receive equal weight, but their failures cannot cancel each other. See [the workflow evaluation contract](../../../docs/mcp-workflow-evaluations.md) for V1–V5/J1–J5, grader invocation, adversarial calibration and the separate learning-review loop. These tests do not replace the historical replay below.

For **each** workflow iteration, follow [private trajectory analysis](../../../docs/mcp-trajectory-analysis.md): record what actually ran and what transcript/audit coverage exists, seal answers before independent judging, compare every criterion on matched requests, investigate pass-to-fail losses despite aggregate gains, and link retrospective price errors to observed draft ordinals without leaking targets to blinded workers. Preserve invalid attempts; development reruns diagnose, while fresh globally isolated cases confirm. Promote only verified, independently reviewed reusable learnings into scoped guidance.

In workflow analysis, compare the unchanged draft, `pricing_decisions` and reviewer handoff. Every finite backend price must remain visible as a proposal, including declined comparisons; nulling it because evidence is weak is a proposal-preservation defect. Explicit incompatible transfers must still be declined. A retained `PRICED_REQUIRES_REVIEW` draft is arithmetic completeness, not adoption/readiness; a numeric-but-declined proposal or held final decision is not completed quoting. Judge evidence/adoption correctness and numeric preservation separately.

Measure the evidence-first mechanism too: duplicate calls, bounded continuation recovery, targeted follow-ups avoided, preserved proposal count, explained changes/declines, time to first usable draft and review corrections. Compare worker guidance, deterministic pricing changes and optional hosted Jev as separate interventions. The normal quote path is offline; better prompts alone do not demonstrate arithmetic improvement. Mock optional Gateway rank/screen/strategy changes first; no paid run is implied by this guide.

Require every mechanical validator and independent judge criterion for a completed all-pass. A judge's acceptance of evidence and communication cannot override a failed request-identity check; keep that case in the attempted denominator.

Run from the repository root in an already provisioned, authorized operator environment. Use owner-only private directories outside the checkout for real targets, PDF-register exports and reports; create new filenames for every run. Select/export a corpus read-only as described by [Polygres](../polygres/SKILL.md). The generator validates provenance **field formats**, `customer_quote_pdf` basis, unknown outcome, five-decimal source precision and cent-rounded extension, then selects one break per normalized part family by salted SHA ranks. It hashes the CSV and writes a v2 JSONL and manifest, but **does not open PDFs/transcripts or recompute their hashes**: authenticity/reconciliation depends on upstream review. It does not write to Polygres or the checkout.

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

The comparison rejects incompatible register/case/target/configuration evidence and checks coverage, median error and all-pass regressions; it is not a calibrated business acceptance test. Changing the register is a **source-basis experiment**: use the [observed-price tool's explicit source-basis mode](../../../docs/observed-price-diagnostic.md) with identical target bytes/IDs/scope/configuration and identical code/lock digest, recording both register hashes. Never weaken `compare.ts`'s different-register rejection or compare internal targets to different PDF targets. Report signed relative error, APE/tails and criterion transitions on the priced intersection, all attempted coverage and newly held/priced cases separately; retain the existing historical 20% criterion. Diagnose one hypothesis at a time. Recency, exact matching, Jev or confidence thresholds are not improvements until matched evidence demonstrates them; no single metric authorizes unattended pricing.

Treat historical experiments as operator-only evidence, not fresh blind targets or proof of any current pricing policy. Test proposed changes against matched cases with unchanged source basis and an independently isolated confirmation set before claiming improvement.

For independent **synthetic order-workflow** checks, run `node estimator/node_modules/tsx/dist/cli.mjs evals/run-orders.ts --tasks evals/tasks --out "$NEW_PRIVATE_BENCHMARK_DIR"`; these grade persisted JSON/Markdown for arithmetic, completeness, blockers and refusal. `node scripts/verify.mjs` covers repository tests and the synthetic benchmark. Neither measures live market-price accuracy. A correct `BLOCKED` outcome is a safety success, not a completed order. All customer requests, source PDFs, transcripts, generated target sets, and reports remain private outside the repository; never tune against a diagnostic split then call it independent validation.
