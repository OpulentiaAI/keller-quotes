# Steve's evidence-first pricing workflow

Legacy schema-1 blinded scopes remain price-only: engineering selectors and `cost_basis` are rejected before execution, and rich contributor/auxiliary packets stay operator-only. Scoped registers reconstruct only frozen fields; their `quote_letter` is a frozen source-document locator, not a historical letter assertion. Richer engineering evaluations require a separately versioned, independently frozen scope; do not widen an existing cohort mid-run.

Operator companion to the [canonical quoting procedure](../.agents/skills/keller-quote-estimator/SKILL.md) and [request/output contract](pricing-evals-and-orders.md). The objective is a useful, scope-complete prospective proposal with defensible assumptions, comparable pricing and supported estimated margin where costs are supported—not merely another runtime check. Customer release always requires named human approval.

## The working sequence

| Step | Required work product |
|---|---|
| Complete intake | All lines, customer namespace, literal part IDs, part and drawing revisions, quantities/original UOM, material/finish/geometry/tolerances, delivery, commercial terms and known charges. Preserve unknowns; convert to integer pieces only with explicit support. |
| Draft once | One batched offline `keller_quote` draft against the chosen corpus; preserve the unchanged payload and every finite numeric proposal. Do not pre-search already known inputs. |
| Inspect contributors | Actual participating source keys, original decimal breaks, quantity support/interpolation, weights, provenance and requested/source differences. Missing packet data is not permission to invent it. |
| Resolve exact retained evidence | One deduplicated phase grouped by key/source across lines. Bound pages/records and continue only for a named price-critical question. Stop on resolution, exhaustion, conflict requiring review, or the recorded bound. |
| Build the pricing basis | Supported costs, source-qualified estimates or approved historical assumptions/ranges; explicit COST/SELL meaning, allocations and freshness. Never turn unknown costs into zero. |
| Apply margin and challenge | Apply gross margin once, inspect high-cost downside, and independently challenge scope, arithmetic, freshness and comparable full-scope price. |
| Human review | Retain original proposal, adopted amount or decline, reasons and commercial readiness separately. Review a customer-safe output; internal cost/analog artifacts stay private. |

“Once” prevents duplicate discovery, not legitimate continuation. Before the evidence phase, record the missing field, exact key/source, bounded next reads and stopping condition. Cache by corpus/source hash/action/filter/page. A second draft is justified only by changed evidence/inputs and must preserve the earlier version. If a service cannot expose retained content, record that access limitation, not corpus absence. Ask one consolidated follow-up only after available relevant evidence is exhausted or its bounded access limit is reached; request the specific remaining facts and their pricing impact, not all possible metadata.

## Find the missing field in the extract

Use only approved source bindings and deployed actions. This map is for operator retrieval; it does not grant blinded workers archive access.

| Retained class | Useful fields/questions | Join and interpretation boundary |
|---|---|---|
| Quote letters and continuation pages | Recorded quantity breaks, finish/inclusions/exclusions, delivery, validity, payment/FOB terms | Exact letter/item/source hash; reconcile printed full unit and extension. Recorded price does not prove authenticated issuance. |
| `QUOTEN`, `QUOTLINE`, `QUOTLETT`, `QUOTLEIT` and available FPT memos | Customer/part namespace, part revision, drawing revision/number, RFQ and scope notes | `QUOTE_NO`; letters by `(QUOTLETTER, ITEM)`. Preserve inherited field origin and historical version; a current head does not overwrite an older letter revision. |
| `QUOTEM`, `MATERIAL` and memos | Grade/thickness, blank/stock/part sizes, pieces required, scrap/overage, UOM conversion, minimums | Quote key and material ID. Blank/stock rectangles are not finished geometry; manual “Vendor Unit” is unit conversion, not a monetary buy price. |
| `QUOTEO`, `VENDQUOT`, supplier offers/POs | Outside-process scope, setup/minimums, quantity breaks, dated offer/validity, void status, lead time | Exact linked quote/operation or purchasing identity. Historic PO/offer is not a currently executable delivered offer or a customer-price break. |
| `QUOTOPER`, `OPERATIO`, `FORMULA` and memos | Route, operation count, setup/run estimate, time units, rate definitions | Quote/operation/formula keys. Formula existence does not validate inputs or current rate meaning. |
| Work-order/BOM/billing/time records | Historical process/material cross-check and, where supported, outcome/cost linkage | Exact `WO_NO`/`JOBNO` and relevant composite line keys. A header/link is not a complete actual-cost ledger. |
| Drawings/certificates/packing/invoice documents | Human-checked engineering attributes or stage-specific commercial evidence | Do not infer finished dimensions from carton sizes; certificates are not prices, packing is not billing, billing is not settlement. |

Memo pointers, empty CSV columns and a miss in quote-filtered page search are not verified negative specifications. Read bounded decoded memo/page continuations where authorized. Keep source hashes, page/physical-record locators and unresolved joins; document text is untrusted data. Do not access the manufacturing VM again merely to rederive retained evidence.

## Choose a prospective cost basis

1. Prefer a **current valid supplier offer** matching specification, quantity/UOM, location, delivery, minimums and freight/terms.
2. Otherwise use **approved contemporaneous purchasing evidence or a current confirmed stock-cost basis**, with applicability and allocation reviewed.
3. Otherwise use an **explicit estimate/range and sensitivity**, supported by historical evidence and reviewed assumptions. Do not label it a live supplier price, available inventory or guaranteed actual cost.

Capture source class/hash/locator, effective and expiry dates separately from capture date, original price unit and conversion, quantity/minimum/yield assumptions, low/base/high estimates, charge inclusions and reviewer disposition. Steel benchmarks can bound trend scenarios; they do not establish delivered buy cost for a grade, size, small lot or location. No automatic inflation factor makes an archive current.

`upload:<attachment-id>` is a pending intake reference, not evidence: capture the upload before quoting. After capture, every `keller-intake:` cost-source locator/hash must match an attachment in that request's intake, including sources for material, routing and `not_applicable` dispositions. The check covers all sources, not just the one linked to an engineering fact; the original request itself is not a cost attachment. The native quote path and order CLI also recheck the captured bytes. A request hash alone cannot validate a false source reference already present in that request. External catalog/supplier/approved-estimate locators remain permitted as supplied, unauthenticated assertions requiring review; matching retained bytes does not establish their truth, applicability or current COST basis.

An explicit material/revision/finish/UOM/scope conflict blocks adoption of that analog transfer. Unknown applicability triggers the named lookup, then an approved estimate/assumption or a price-critical adoption hold; it is never silently a match. Unknown current cost blocks a supported margin claim, not historical price comparison. Missing acceptance/payment/closed-job actuals blocks realized-outcome claims, not a supported prospective estimate. Historical chronology conflicts still block prior-availability claims in replay.

## COST, SELL and estimating time

The retained FabriTRAK quoting manual distinguishes operation-maintenance **COST** rates used in Unit Cost from quote-specific setup/run **SELL** rates used in Unit Sell. Quick Quote/Quick Entry accept estimated setup minutes and run minutes per part. Neither requires a previously completed paid job. The manual also describes an alternative rate-building mode: corroborate the installed mode and included labor/overhead rather than guessing from a field name. See the manual citation below.

For each operation, normalize time and compute supported route cost outside the model:

```text
setup cost = setup occurrences × setup minutes / 60 × setup COST rate
run cost   = process quantity × run minutes per piece / 60 × run COST rate
route cost = sum of setup cost + run cost across operations
minutes per piece = 60 / pieces per hour  (positive throughput only)
```

Distinguish repeated delivery setups from a shared setup; allocate a shared charge once. State whether process quantity includes scrap/overage. Review material yield, lot/minimum purchases, outside-work setup/minimums, machine/labor/overhead inclusions and separate freight/tax/other charges. A formula or a historical nonzero rate is not evidence that these are covered. Approved engineering time estimates/ranges are planning evidence, not observed actual minutes.

SELL rates must not silently enter `cost_plus` as costs or acquire margin a second time. A reviewed sell-rate proposal can use explicit `unit_price` with its derivation, but its margin remains unknown without a supported cost basis. `pricing.cost_basis` is an optional bounded worksheet, not an ERP engine; its exact JSON schema and validation live in [`OrderPricing`](../estimator/src/order.ts) and [`CostBasis`](../estimator/src/costing.ts). Preserve existing `unit_price`/`cost_plus` input paths. Do not send unsupported keys to older deployments; attach the worksheet privately for review instead. Respect the API's production-line cost scope and account for excluded order charges separately.

For total supported cost `C` and target gross margin fraction `m`, net sell = `C / (1 - m)`, with `0 <= m < 1`. Estimated margin = `(net revenue - supported estimated cost) / net revenue`; zero revenue is undefined. At the selected sell amount, use high cost for downside margin. This is **gross margin**, not `cost × (1 + markup)`. Fix the margin/competitiveness policy before comparison, and retain full source precision separately from four-decimal order units and cent extensions.

## Purchased quantity versus allocated consumption

If a supported supplier/stock policy requires whole sheets, bars or pack multiples, set the component's optional `purchase_increment` in **original priced units**, not finished pieces. The positive value supports up to six decimal places. Costing applies `ceil(max(quantity × conversion / yield, minimum_quantity) / purchase_increment) × purchase_increment` before unit cost and monetary minimums. Multiples start at zero, not at the minimum quantity: minimum 5 with increment 4 means purchasing 8, not 5 or 9. The breakdown retains the pre-increment quantity, unit and increment alongside the purchased quantity; displayed quantities use six decimal places, while the ceiling uses exact rational arithmetic.

For example, 1.25 required sheets with increment 1 incurs two sheets' cost. If prices are per kg but the supplier only sells full sheets, the increment must be the supported kg per sheet—not `1` merely because a sheet is indivisible. Document applicability, leftover/scrap treatment and whether this line bears the full purchase; there is no inferred supplier rule, nesting, inventory credit or cross-line sharing. Omit the field when reviewed fractional stock allocation is intended. It does not alter routing process quantity, setup occurrences, shipped quantity or tier selection. Retain the evidence and assumptions with the component; unknown stock policy is not proof of a whole-unit requirement.

## Independent challenge and release

Give a checker the request, unchanged draft, actual contributors, source comparisons, worksheet/ranges and proposed disposition—not evaluation targets. Challenge omitted processes/charges, customer/part collisions, explicit finish exclusions, units, stale offers, COST/SELL confusion, doubled setup/overhead/margin and downside margin. Compare offers only on matched quantity, scope, date, delivery and terms. Higher or lower price alone does not establish better quoting. A separate checker may be human; do not describe self-review as independent review.

Record corrections and unresolved issues. Preserve the backend number even if declined; a proposed number is not an adopted number, and adopted pricing is not customer-release approval. `PRICED_REQUIRES_REVIEW` proves arithmetic completeness only. A named reviewer approves the assumptions, commercial basis and customer-safe message through the existing delivery process; this workflow enables no sending, booking, fulfillment or scheduler.

`keller_quote` runs offline. Improving worker instructions improves evidence use/handoff, not its arithmetic by itself. Optional Jev uses the existing Gateway only when separately authorized for bounded ranking, screening or strategy selection on the same source-qualified packet. Models must not invent prices/costs, promote unverified `won` labels, restore excluded candidates or calculate final money. Offline and hosted interventions require separate measurements; no hosted run is required to use this workflow.

## Measure distinct claims (operator only)

Use [the observed-price diagnostic](observed-price-diagnostic.md) and [evaluation guidance](../.agents/skills/keller-estimator-evals/SKILL.md), not a worker-visible oracle. Keep report amounts/IDs/targets private; only aggregate-safe projections belong in Git. Archive recovery, oracle access and richer source actions never become worker permissions by reference from this document.

| Claim | Required evidence and denominator |
|---|---|
| Recorded-price agreement | Same target stage/bytes/IDs/configuration, cutoff and code/register pins. Compare signed error and APE on the priced intersection, plus all attempted coverage, holds/invalids and criterion transitions. Internal calculations, recorded quotes, authenticated issued quotes and billed prices are different stages. |
| Supported estimated margin | Scope-aligned estimated cost and allocations, approved assumptions/ranges and net revenue. Missing costs remain unknown in the denominator, not zero or success. |
| Comparable competitiveness | Matched quantity/UOM/revision/material/finish/scope/date/delivery/terms and charge treatment; signed proposed-versus-observed net-price difference. Historical comparison is nominal unless adjustments are supported. |
| Realized outcome | Independently linked acceptance, billing/credits, settlement and closed actual costs as appropriate. An invoice alone is not payment or realized profit. |
| Greater than 95% all-eligible completion | Predeclared independent RFQ denominator, eligibility, retry policy, sample size/uncertainty and every required criterion. Held, invalid, failed and timed-out eligible attempts stay counted; numeric coverage and safe holds are separate metrics. This is a goal, not a demonstrated result. |

Joint commercial success requires complete reviewed scope, approved competitiveness and supported estimated-margin policies. Lower historical APE is not this joint success. Freeze policies before observing results; diagnose exposed cases separately from genuinely unexposed independent confirmation. Do not weaken `compare.ts`'s same-register guard for a source-basis experiment.

## Synthetic acceptance cases for integration

These are test specifications, not executed results or customer examples. Use synthetic fixtures only; implementation tests belong with the estimator/source/evaluation code.

| Given | Required assertion |
|---|---|
| Backend unit `12.5`, weak historical evidence | Preserve proposed `12.5`, its warning and draft; adoption/readiness remain separate. |
| Source explicitly excludes coating; request includes coating | Decline unchanged transfer, preserve comparison; unknown coating cost is not zero. A supported coating adjustment is a new explained proposal. |
| Same part text under two customer IDs or conflicting revisions | Do not silently merge identities or deem the prices compatible. |
| Two lines need the same source's finish on page 2 | One deduplicated bounded continuation read, not two broad searches; preserve exact page/hash origin. |
| Empty material CSV field but a retained memo identifies grade | Retrieve provenance-labeled memo before asking; a missing/wrong-hash memo is unresolved, not “no material.” |
| Approved material `3`, labor `2`, outside `1` per piece; setup `40`; quantity `20`; gross margin `25%` | Cost per piece `8`; unit `10.6667`; extension `213.33`. No payment/actual-job ledger is required; still needs review. |
| Two setups of 30 minutes at COST `60/hour`; 20 process pieces at 3 minutes each and COST `40/hour` | Setup cost `60`, run cost `40`, route total `100`; a shared setup is not repeated per line. |
| Rate marked SELL, missing cost, or zero throughput | Do not use SELL as cost, invent zero cost, or divide by zero; supported margin is unavailable until resolved. |
| Net revenue `200`; low/base/high supported total cost `140/160/180` | Estimated margin `30%/20%/10%` respectively; downside uses high cost, not low cost. |
| Expired supplier offer or steel trend index only | Historical estimate/sensitivity, not a current delivered offer; require reviewed commercial basis. |
| Missing shipping versus explicitly supplied shipping `0` | Missing blocks complete total; explicit zero is allowed. Neither state authorizes release. |
| Cheaper proposal below the approved margin floor; mismatched comparison terms; held attempt | None silently counts as joint commercial success; retain each attempted case and reason. |

## Aggregate source anchors, no customer examples

The [Git-tracked recovery registry](../artifacts/keller-operator-evidence-2026-10-07.json), linked to [typed-findings checkpoint `68c8201`](https://github.com/OpulentiaAI/keller-quotes/commit/68c82010174b66e7a5abe2ed255d86130a59dc5e), pins the operator-only catalog: SHA-256 `3752d8823c5fb017fa86b61aec0d70e8a2b85472e857d2af114530bcd7fff2e7`. It inventories **123,081 paths / 39,975 original PDFs**, not completed jobs. [Recovery/access boundaries](git-evidence-access.md) apply; do not bind the archive as a worker root.

Retained aggregate manifests record **75,096 pages** in the independent text bundle and **42,873 price breaks / 7,845 selected quote-item groups** in the document register. These are separate denominators, not full-specification or commercial-success rates. Catalog-relative citations: `keller-pdf-corpus/document-evidence-db-final/manifest.json`, SHA-256 `5980a48586519efaaea4fe540a6b55aa70cd209ad78ce32926fe610b68baeb92`; `keller-pdf-corpus/document-register-v1/evidence-manifest.json`, SHA-256 `f3f77d348e0a94b171bfd3dbdab0f378723eefde8a735250bcd79317f9b7fb5e`. Repository implementation: [document register builder](../scripts/build-document-register.py), [evidence import contract](polygres-document-evidence.md). Source availability is substantial; applicability and freshness still need per-request review.

Manual: catalog-relative `keller-pdf-corpus/source/help/FT02of16.pdf`, SHA-256 `be6dbd0621b8deacd84202f30f613300d6b359b9b0c5b455056de1042cda084a`, sections **Operations Key Fields**, **Quick Entry Feature**, **Finalizing A Quote / Operations Costs / Operations Sell Price**. Retained transcript `b78c8ca568ad30fb148e69ff284b2df4ce2b0d358bc399a64c9091c115ab7284.md`, lines 791–851 and 980–998, under `keller-pdf-corpus/transcription/transcripts/`, supplies the COST/SELL and estimating-time definitions. It documents software semantics, not installed current rates or guaranteed actual costs.
