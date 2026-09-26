# keller-estimator

Agentic pricing-request → quote estimator for C. Keller Mfg., built on the
**Metalsoft FabriTRAK quoting register** (179,608 quote lines / 40,111 quotes
from `C:\Vftw\KELLER`, extracted 2026-09-21 — see
[keller-quotes](https://github.com/OpulentiaAI/keller-quotes)) and **TypeSafe
Jev** (`typesafe-ai/jev` via Vercel AI Gateway) for bounded judgment.

## Pipeline

```
request.json (customer + parts[part_no, description, qty, material, drawing_ref])
  → retrieve   deterministic analog candidates: exact/normalized part_no,
               drawing_no match (the "visualization" link — customer drawing
               numbers match quoted drawings), description-token overlap,
               same-customer / material / won-quote bonuses
  → jev.rank   one bounded `choice` question over the top-8 candidate
               descriptions → calibrated ordering + probabilities
  → jev.screen boolean "is this a genuine analog" on the top candidates;
               rejects are dropped
  → jev.choose bounded choice of pricing strategy per line:
               latest | median_won | curve_fit | conservative
  → price      per-analog log-log interpolation of that quote's own qty/price
               breaks to the requested qty → weighted median (weights:
               similarity × recency × won-bonus × Jev probability) →
               unit_price + p25/p75 band + confidence
  → quote      JSON (and optional CSV) with per-line price, analogs,
               confidence, and warnings
```

Jev only ever sees descriptions and picks among prevalidated options — it
never invents prices or tool inputs. Without `AI_GATEWAY_API_KEY` (or with
`--offline`) the same pipeline runs fully deterministically with the
deterministic ranking/`median_won` fallbacks.

## Usage

```bash
npm ci
# the default register resolves relative to the module — or pass --register
npm run estimate -- examples/request.json --csv quote.csv
# Jev enabled automatically when AI_GATEWAY_API_KEY is set
```

Request format: `customer` / `customer_id` (optional, boosts same-customer
history), `parts[]` with `part_no`, `description`, `quantity` (required),
`material`, `finish`, `drawing_ref`, `notes`.

Output per line: `unit_price`, `extended_price`, `price_low`/`price_high`
(weighted p25/p75), `confidence` (0–1), `method` (which strategy ran),
`status_basis` (`jev+…` vs `fallback:…`), top `analogs` with Jev
probabilities, and `warnings` (e.g. "no won-quote analogs").

Quote-time historical replays can pass `EstimateOptions.asOf` (`YYYY-MM-DD`): only quotes/revisions/letters dated before the cutoff are used, and wins are visible only if their won date precedes it. Recency is computed at the same cutoff. The live CLI uses all available history unless the caller supplies `asOf` through the library.

## Interpretation notes

- Prices are **as-quoted historically** — no inflation normalization is
  applied. A 1994 analog produces 1994 dollars; the recency weight and the
  p25/p75 band make that visible, and `confidence` drops when the newest
  analogs are old. Treat stale lines as "needs markup review", not gospel.
- `status` in the register is `won`/`open` only — FabriTRAK's lost-quote
  table (QUOTEHN) is empty, so "open" includes silently-lost history.
- `drawing_ref` accepts a drawing number (e.g. `"RAL-0214"`); it is matched
  against the register's `DRAWING_NO` field. Raster/PDF drawing analysis
  (dims/materials from a scan) is out of scope — feed extracted attributes
  in via `material`/`notes`.

## Layout

- `src/register.ts` — CSV → grouped quotes (one group per quote_no+item, all qty breaks) + indexes
- `src/retrieve.ts` — deterministic candidate retrieval/scoring
- `src/jev.ts` — `typesafe-ai/jev` wrapper (`experimental_evaluate`, gateway key, 15s deadline, zero retries)
- `src/price.ts` — per-quote qty interpolation + weighted strategies + confidence
- `src/estimate.ts` — orchestration
- `src/cli.ts` — `estimate <request.json> [--register …] [--csv out] [--offline]`
- `test/estimator.test.ts` — vitest suite (register, retrieval, pricing, end-to-end offline)

## Complete order proposals

`src/order-cli.ts` assembles every request line, explicit shipping/tax, additional charges, and a reconciled total into `order.json` and `order.md`. Lines may use offline historical analogs, an explicit proposed unit price, or a supplied cost build-up. Missing prices or charges produce `BLOCKED` with no grand total, rather than a partial total labeled complete. Every priced proposal remains subject to human review.

```bash
# from estimator/, with an existing private parent output directory
npm run order -- examples/order-request.json --register ../quotes.csv --out ../out/demo-order
```

The example is synthetic. See [the order schema, evaluation tasks, and comparison workflow](../docs/pricing-evals-and-orders.md) before using real inputs. The older estimate CLI and inbox worker still produce quote drafts, not this order artifact.

## Verification

From the repository root, run the same offline verification used by CI:

```bash
node scripts/verify.mjs
```

This runs estimator/order/eval tests, the build and separate evaluation typecheck, compiled CLI smoke, local automation tests, and the synthetic request-to-order artifact benchmark. For database verification and replay commands, see [execution and release verification](../docs/execution.md). `npm test` from `estimator/` remains the focused test command.

The repository root's `scripts/keller-local.mjs` and [operator guide](../docs/local-automation.md) provide offline readiness checks and a durable, manual-review-only request queue.
