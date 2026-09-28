---
name: keller-quote-estimator
description: Prepare reviewed Keller customer-quote drafts and complete internal priced-order proposals using explicitly chosen historical evidence or operator-supported current costs; use for pricing requests and RFQs.
---

# Price a Keller request without inventing evidence

Start with [the register's price-basis rules](../keller-quote-register/SKILL.md). For historical **issued customer prices**, prefer a selected `customer_quote_pdf` corpus exported read-only to a private CSV by [the Polygres guide](../polygres/SKILL.md). The CLI otherwise defaults to frozen `internal_quote_calculation` prices through its symlink; that is a separate fallback diagnostic, **never** a silent substitution or a validated current sell price. Document prices have unknown outcomes, and neither historical basis validates today's material/labor/routing costs.

In the Ars Umbris `Keller Codex` profile, `keller_quote` is the runnable internal order-draft path: supply an explicit approved customer-PDF corpus ID, a JSON `OrderRequest`, and a named human reviewer. It invokes the offline order CLI against a read-only corpus export, accepts supported operator price/cost inputs, and returns structured `order`, `markdown`, `review`, blockers/state, and private artifact references. Those response fields contain sensitive customer, analog, and cost details: keep the entire tool result in an approved private review channel, never forward its Markdown to a customer. `BLOCKED` is incomplete; `PRICED_REQUIRES_REVIEW` is complete arithmetic, not an approved or delivered quote. For source inspection beyond Polygres, `keller_sources` provides bounded read-only source-set listing, file reads, DBF schema, and exact-quote DBF rows; historical routing/material records are not verified present-day rates. The CLI steps below remain the standalone operator workflow, not the only Ars Umbris draft interface.

## Intake and evidence review

Preserve every supplied customer_id when building keller_quote's OrderRequest, even though the schema marks it optional. Compare supplied identity fields with the returned order.request before handing the draft to review.

Record customer/RFQ/date, stable line IDs, part number **and drawing revision**, quantity and UOM for each line, material grade/thickness/yield, finish/outside work, tolerances, lead time/delivery, and unresolved specification questions. Ask for missing information before asserting equivalence. An exact normalized part number across different customers, revisions, materials or UOM does not prove interchangeability. A drawing/PDF needs human-checked extracted attributes; the estimator does not interpret drawings. Never access the remote manufacturing host, source DBFs, or PDFs merely to rederive already verified historical evidence.

For a historical draft, pin the selected register path/hash and inspect each usable analog's quote letter/date, source PDF/transcript hashes and source price field. Check revision, material, process, UOM, quantity-break curve and source-event timing; retain the full source unit precision and validate the printed extension. Do not use unverified `won`/`open` as sales outcomes, invoice or supplier-PO amounts as quote prices, or mix internal and PDF prices within a curve. A missing/weak/old/mismatched analog means **hold that line** for a human-supported cost build or explicit operator price; it is not license to invent a price. `confidence` and `price_low`/`price_high` are uncalibrated diagnostics, not approval gates or promised customer ranges.

For Keller historical eligibility, reconcile the PDF's printed By date with its Inquiry Date and register dates. Conflicting dates do not establish prior availability; retain the chronology blocker rather than treating the inquiry date as verified issuance.

In reissue handoffs, state the PDF's displayed unit beside the verified full-precision unit and explain any difference. Reconcile quantity × full unit to the printed extension; extension cent-rounding does not explain a separate unit-display discrepancy.

Before replacing a Keller evidence-shortage hold with an explicit price, record a source-versus-request comparison for material, finish, revision and geometry, with evidence for each claimed match or justified adjustment. Unresolved price-critical gaps keep the line held.

For Keller analog transfers, an unknown material or finish adjustment is not a zero adjustment. Do not copy an unchanged source unit because its page is silent about the requested process; retain the hold until compatible issued evidence or authorized costing supports the amount.

In analogy-based Keller handoffs, show the page's displayed unit beside the verified full-precision unit and reconcile quantity times full unit to the printed extension. Explain any display difference only from verified evidence; cent-rounding of the extension is a separate operation.

Run the estimate CLI only after choosing a register. This minimal example is synthetic and intentionally forces the deterministic offline path; put real customer requests/outputs in approved private storage outside the checkout:

```json
{
  "customer": "SYNTHETIC CUSTOMER",
  "parts": [{"part_no": "SYNTHETIC-PART", "description": "Demo bracket",
             "quantity": 10, "material": "Example steel", "drawing_ref": "DEMO-REV-A"}]
}
```

```sh
# Run from repository root after: (cd estimator && npm ci)
node estimator/node_modules/tsx/dist/cli.mjs estimator/src/cli.ts \
  "$PRIVATE_REQUEST_JSON" --register "$SELECTED_VERIFIED_CSV" --offline
```

`--register` must be explicit. If no verified register is available, either hold or deliberately choose `--register quotes.csv --offline` and label **every** resulting figure internal-calculation-only. `AI_GATEWAY_API_KEY` can otherwise enable hosted Jev; `--offline` removes that dependency. A separately authorized `--jev` evaluation would be needed to demonstrate ranking value. The estimate CLI's `total` can sum priced lines despite missing prices, so do **not** treat it as a complete order total. Preserve private analog details for the reviewer, but never cite another customer's internal quote, cost, identity, or source PDF to the customer. Prepare a separately reviewed customer-safe explanation through the approved channel.

For a fresh cost-backed proposal, get operator-supported **current** material price and UOM conversion, yield/scrap, minimum lot, actual routing/labor/setup, outside processing, and lead time. The 13 active manufacturing DBF formulas alone do not verify present rates/times; absent inputs and independent positive actual operation times block a cost guarantee. Do not fill those gaps by extrapolating a frozen formula or guessing inflation.

## Complete internal priced order

Use `estimator/src/order-cli.ts`, not the estimate CLI, for a requested complete priced-order proposal. It requires stable `line_id`s, order/date/customer, positive integer **piece** quantity, and explicit shipping/tax **amounts** (including zero only when the operator explicitly supplies zero). For non-piece UOM, clarify and convert with the operator before submitting; do not guess a conversion. Each line may use historical analogs with no `pricing`, an explicit positive operator `unit_price` (up to four decimals) plus reason, or a supported `cost_plus` build. Cost-plus takes `material_per_unit`, `labor_per_unit`, `outside_per_unit`, `setup_total`, `margin_pct`, reason; its divisor `1 - margin_pct/100` treats margin as **gross margin**, not markup. Source PDF unit evidence may have five decimals, but the order's operator-entered unit price is limited to four: preserve the original precision in evidence and review the rounding explicitly.

```sh
node estimator/node_modules/tsx/dist/cli.mjs estimator/src/order-cli.ts \
  "$PRIVATE_ORDER_REQUEST_JSON" --register "$SELECTED_VERIFIED_CSV" \
  --out "$NEW_PRIVATE_ORDER_DIRECTORY"
```

See the fully synthetic [order request example](../../../estimator/examples/order-request.json) and [input/output contract](../../../docs/pricing-evals-and-orders.md). The output directory must not exist. Exit `3` / `BLOCKED` still writes internal artifacts but **no total** for any unresolved line, shipping or tax; exit `0` / `PRICED_REQUIRES_REVIEW` is arithmetically complete, **not approved**. Validation failure exits `2`. Named human review must confirm scope, costs, evidence, price, terms and customer-safe communication before any existing approved external-delivery process. `order.json` and `order.md` expose costs, analogs, and history: never send them directly to a customer. This workflow does not book an order, email a customer, accept payment, initiate fulfillment or enable a scheduler. See [the eval guide](../keller-estimator-evals/SKILL.md) for evaluation procedures and limitations; historical performance evidence is operator-only.
