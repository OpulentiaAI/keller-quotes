# Pricing evaluations and complete order proposals

Two different questions need different evaluations: **is the historical price accurate?** and **did the system produce a complete, internally consistent order proposal?** A perfectly formatted order can still contain a bad estimate. Do not combine those scores or call a synthetic workflow pass proof of market-price accuracy.

This design adapts Harvey Labs' [task-local rubrics and deliverable-aware all-pass grading](https://github.com/OpulentiaAI/harvey-labs/blob/845a08840869b21a5c11958aae58bf5f00a7b775/docs/eval-strategies.md). Harvey uses an LLM judge for legal work; Keller uses deterministic checks for prices, arithmetic, completeness, source evidence, and readiness. No legal task data or model-judge dependency is imported. Keller's grouped diagnostic split and paired baseline comparison are additions, not features copied from Harvey.

## Request → priced order

Install with `cd estimator && npm ci && cd ..`, then run from the repository root:

```sh
node -e "require('node:fs').mkdirSync('out', {recursive: true})"
node estimator/node_modules/tsx/dist/cli.mjs estimator/src/order-cli.ts \
  estimator/examples/order-request.json --register quotes.csv --out out/demo-order
```

The CLI writes **`order.json` and `order.md`** into a new directory. The JSON is the machine-readable internal artifact; the Markdown shows every line, price source, totals, blockers, warnings, and provenance for review. Existing output directories are refused, even for a previous failed or blocked run. Choose a new directory for a revised request. The example uses explicitly synthetic operator prices and costs, not a customer price recommendation.

After `cd estimator && npm run build`, the compiled entry point is `estimator/dist/src/order-cli.js` from the repository root. `npm run order -- <request> --register <CSV> --out <NEW_DIRECTORY>` also works from `estimator/` with paths relative to that directory.

### Input contract

```json
{
  "order_id": "EXAMPLE-001",
  "quote_date": "2026-09-26",
  "customer": "EXAMPLE CUSTOMER (SYNTHETIC)",
  "parts": [
    {
      "line_id": "L1",
      "part_no": "DEMO-BRACKET",
      "quantity": 10,
      "pricing": {
        "method": "unit_price",
        "unit_price": 12.3456,
        "reason": "Synthetic operator proposal, not an approved customer quote"
      }
    }
  ],
  "charges": { "shipping": 0, "tax": 0 }
}
```

Order/date/customer and unique, stable `line_id` values are required. Each part needs a part number or description and a positive integer piece quantity. The remaining part fields match the estimator request (`material`, `finish`, `drawing_ref`, `notes`). Repeated part numbers with different line IDs remain separate order lines.

Every line follows exactly one pricing path:

| Input | Price source | What the operator must supply |
|---|---|---|
| No `pricing` field | Offline historical analog | Part attributes. Retrieval excludes quotes/revisions/letters on or after `quote_date`; no usable price leaves the line unresolved. Historical dollars are not current-cost verification. |
| `pricing.method: "unit_price"` | Explicit sell-price proposal | Positive `unit_price` with up to four decimal places, and a nonblank `reason`. Supplying it is not approval. |
| `pricing.method: "cost_plus"` | Cost build-up | `material_per_unit`, `labor_per_unit`, `outside_per_unit`, `setup_total`, `margin_pct`, and a nonblank `reason`. These are operator-supplied costs, not values invented from an old quote. |

Cost build-up uses `(material + labor + outside + setup / quantity) / (1 - margin_pct / 100)`. `margin_pct` is **gross margin**, not markup, and must be at least zero and below 100. Costs cannot be negative; a zero resulting sell price is invalid. The sell price is rounded half-up to four decimals and the displayed sell price × quantity is rounded half-up to cents. Totals sum those cent-rounded lines and explicit charges; arithmetic that cannot be represented safely is rejected.

Shipping and tax are **amounts**, not inferred rates. An explicit `0` means the operator proposes no charge; missing or `null` means unknown and blocks completion. Optional `additional_charges` is an array of `{ "label": "Tooling", "amount": 25 }`; all charge amounts are nonnegative dollars with at most two decimals. There is no tax engine, shipping-rate lookup, discount policy, or current material/labor feed.

### Output and exit status

| Exit | State | Meaning |
|---|---|---|
| `0` | `PRICED_REQUIRES_REVIEW` | Every requested line, shipping, and tax has an explicit amount and the total reconciles. This is a complete internal proposal, not an accepted or released order. |
| `3` | `BLOCKED` | Artifacts exist, with actionable blockers and `total: null`. Missing prices never become zero to manufacture completeness. |
| `2` | Validation/runtime error | The command could not produce the order; read stderr and correct the input or environment. |

`priced_subtotal` is explicitly a diagnostic sum of priced lines; it is not an order total. `subtotal` is null if any line is unpriced. `requires_human_review` is always true. The internal artifact preserves operator cost inputs, reasons, historical analogs, and request data, so **do not forward it directly to a customer**. Request provenance is SHA-256 of `JSON.stringify(request)`, not the original file's whitespace; the CLI hashes the actual register bytes. The quote date and offline mode are pinned alongside those digests.

This CLI is separate from the older inbox worker, which still emits `QuoteEstimate` drafts and `DRAFT_REQUIRES_MANUAL_REVIEW` receipts. Do not feed the new order schema into that worker and assume it enforces these completeness rules. The new CLI does not install a producer/scheduler, approve prices, book an order into FabriTRAK, send email, collect payment, or trigger fulfillment.

## Historical price accuracy

```sh
node estimator/node_modules/tsx/dist/cli.mjs evals/run-eval.ts \
  --register quotes.csv --report out/pricing-baseline.md
```

The fixed 250-case set stays unchanged. A schema-version-2 report contains source-register and evalset digests, relevant estimator/evaluator source and lockfile digest, effective configuration, per-case evidence and criteria, aggregate metrics, and slices. The source quote is excluded; default replay applies the quote-date cutoff and hides outcomes unavailable then. `--retrospective` is explicitly future-visible and is not comparable to the default. `--jev` requires credentials and is a separately authorized provider-backed experiment; all commands in this guide are offline.

Each historical case has required checks for a finite positive price, source exclusion in exposed analogs, cutoff evidence, error within ±20%, and a reconcilable extension. **All-pass is measured over all cases**, including unpriced failures. Accuracy statistics also report the priced-only denominator so coverage cannot disappear from the result. Exposed analogs do not carry full revision history: the grader describes that limitation rather than claiming an independent true-backtest proof.

Reports break results down by quote era, quantity band, won/open outcome cohort, exact-part evidence, confidence band, and a reproducible development/holdout partition grouped by normalized part number. That split is diagnostic, **not a blind untouched holdout**: this fixed set has already been inspected. Small slices and the won/recent-biased sample cannot establish natural production prevalence. The set also lacks description-only and material-bearing requests; synthetic workflow tasks cover those contracts, not their real-world accuracy.

After a candidate change, run the same command with a new report filename, then compare:

```sh
node estimator/node_modules/tsx/dist/cli.mjs evals/compare.ts \
  out/pricing-baseline.json out/pricing-candidate.json \
  --report out/pricing-comparison.md --fail-on-regression
```

Comparison requires matching source data, case selection, actual prices/quantities, cutoff mode, and effective configuration. Different source-code digests are expected. It reports coverage/error/all-pass changes and improved/regressed cases and slices. `--fail-on-regression` makes coverage loss, median-error increase, or all-pass loss fail the command; it is an engineering regression gate, not a calibrated business acceptance threshold. Do not repeatedly tune against the diagnostic holdout and then advertise it as independent validation.

## End-to-end artifact benchmark

```sh
node estimator/node_modules/tsx/dist/cli.mjs evals/run-orders.ts \
  --tasks evals/tasks --out out/order-benchmark
```

Each directory in `evals/tasks/` contains a schema-version-1 synthetic `task.json`, `request.json`, and `register.csv`. The solver receives only the request/register, never the grading expectations. The runner writes artifacts first; a separate grader reloads those artifacts and checks declared criteria. Every required criterion must pass for the task to pass. Missing/corrupt artifacts and invalid rubrics cannot count as passes.

`scores.json` preserves criterion verdicts/reasons, input/output hashes, and an implementation/source/lockfile digest; `report.md` gives the all-pass result and diagnostics. Completely priced orders, correctly blocked requests, and correctly rejected invalid requests are counted separately. A correct refusal is a safety success, **not a completed order**. Negative regression tests alter persisted JSON and Markdown independently to prove that omitted lines, false readiness, wrong displayed prices, and inconsistent totals fail grading.

`node scripts/verify.mjs` includes the order/eval tests, both TypeScript checks, compiled CLI smoke, and the synthetic artifact benchmark. Keep generated real requests, orders, and evaluation outputs under an approved private runtime directory (`out/` is gitignored). Version the small synthetic task inputs and grader changes; do not commit customer artifacts or replace the frozen historical set to improve a score.
