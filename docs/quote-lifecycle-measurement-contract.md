# Quote lifecycle joins and measurement contract

This is a proposed operator-reviewed contract, not an implemented financial join or evidence that invoices were paid. The retained data supports exact quote-level job pointers and bounded original invoice-content checks; it does not yet support a versioned accepted-line, complete receipt/credit allocation or complete realized-cost dataset.

## 1. Preserve the stage, line and version

Assign one immutable `lifecycle_line_id` to the original requested customer line. Keep separate `stage_event_id`, `stage_line_id` and `stage_version_id` values for the RFQ, prediction, customer quotation, accepted order/change, manufacturing allocation, invoice/credit and receipt/application stages. A new quote, order change, invoice correction or reversal is a new version/event rather than an overwrite.

Each priced stage line needs the customer identity, source line identity, part, revision, drawing/specification version, material/finish/process scope, quantity, quantity tier, UOM, currency, unit-price basis, included/excluded charges and event date. Record source-observation dates and independently established effective/availability dates separately. A date stamp, file mtime or ingestion timestamp is not a first-issued or historically available version.

The prediction stage additionally freezes model/code version, evidence selection, knowledge version, cutoff, request version, predicted unit price/cost and hold/error state. Record whether the target is a customer-quotation price, an internal calculation or an independently supported manufacturing cost; do not combine those target populations into one error score. Future invoice, acceptance and cost evidence remains operator-only and outside blinded prediction inputs.

Native source identifiers remain strings with leading zeros intact. Unknown and blank identity fields are not wildcards or matching revisions. Preserve raw field values privately while keeping public outputs at aggregate grain.

## 2. Supported native joins and unresolved links

| Bridge | Join contract | Current source limit |
|---|---|---|
| Letter header to letter line | `QUOTLETT.QUOTLETTER = QUOTLINE.QUOTLETTER`; retain letter-local `QUOTLINE.ITEM`. | The letter-local item is not `QUOTEN.ITEM_NO` or a sales-lot item number. |
| Letter line to letter quantity break | Match `(QUOTLETTER, ITEM)` to `QUOTLEIT`, then retain the explicit quantity break and physical source-row identity. | Duplicate breaks or lines require source review; selecting a nearest quantity or latest date is not identity proof. |
| Letter line to calculation quote | `QUOTLINE.QUOTE_NO = QUOTEN.QUOTE_NO`, with quote item, customer, part, revision and drawing checks. | Internal calculation price and customer-letter price remain different source bases. |
| Quote to sales order | Exact `SOMAST.QUOTE_NO`, `COMP_ID` and `PART_NO`; retain each matching native order record and `JOBNO`. | `QUOTLETT` is blank in all 99,920 captured active sales-order records, so no accepted letter/version is supplied by that field. |
| Sales order to lot and work order | Nonblank `JOBNO` across SOMAST/SOLOTS/WOJOBS; customer across SOMAST/SOLOTS/WOHEAD; nonblank `WO_NO` across SOLOTS/WOHEAD/WOJOBS; part across SOMAST/WOHEAD; nonblank `LOT` across SOLOTS/WOJOBS. | This is quote-level ERP-pointer evidence; lot allocation, accepted order/version and full manufacturing identity still need review. |
| Job to invoice line | Match a role-verified original invoice's printed Job # to exact native `JOBNO`, then verify recipient/customer identity, part, revision, PO, shipment, quantity/UOM/currency and invoice-line/lot allocation. | One example has exact printed-job/part/revision matches. No population invoice parser, invoice join or allocation has been validated. `SOLOTS.INVOICE_D` is not an invoice ID. |
| Invoice to cash/credit | Exact operator-authoritative invoice ID and line/header key, plus distinct receipt, application and credit event IDs and reversal references. | Required table/report data has not been supplied; filenames and invoice totals cannot provide this bridge. |
| Work order to realized cost | Exact closed-job/work-order/lot scope, with complete posting enumeration, signed reversals and explicit component/allocation semantics. | Stored COST/hours fields and the available bill/BOM rows do not establish complete posted actuals. |

Represent many-to-many relationships in an explicit allocation bridge, not an unrestricted relational product. Each bridge row retains its source references, review state, allocated quantity/UOM, amount/currency, applicable stage versions and unresolved reason. Reconcile allocations to both parents, and distinguish legitimate split lots, multiple shipments and replacement invoices from duplicates.

The accepted-order source must explicitly identify the selected quote/letter version and accepted customer line. An exact quote number with several letter versions, a blank letter pointer or a matching part is insufficient. `PO_REC`, `DATE_CONF`, `STATUS`, `CLOSE_DATE` and invoice-date-looking values remain stored observations until an independently reviewed business event establishes their meaning.

## 3. Separate five measurements

### Prediction error

Use an independently reviewed target at the same requested line, version, quantity tier, scope, UOM, currency and price basis as the frozen prediction. For positive finite target unit price `t` and finite prediction `p`, report signed relative error `(p - t) / t`, absolute relative error `abs(p - t) / t`, signed bias and the underquote share. A quantity-weighted error is `sum(abs(p - t) * quantity) / sum(t * quantity)` only when those quantities share the declared target scope.

Publish target-eligible coverage and successful-prediction coverage separately. The all-request denominator retains holds, missing targets, errors, invalid attempts and timeouts; the priced-only error denominator contains only declared comparable cases. Do not insert zero prices, exclude inconvenient cases silently or reuse a quotation target as complete-cost ground truth. Historical internal-calculation replay and customer-PDF price replay remain separately labeled. Invoice variance is a billing-stage measure, not automatically a prediction error.

### Scope and accepted-price changes

Record changes between the quoted request version and accepted order versions explicitly: drawing/revision, quantity tier, material/process/finish, delivery requirements, packaging, terms and included charges. Report scope-change incidence over all linked lines, and separately report approved same-scope commercial price changes and changed-scope amount deltas. A changed-scope line is ineligible for the original same-scope prediction-error measure until a separately versioned target is supplied. A numerical difference alone does not identify the cause or monetary effect of a scope change.

### Issued quotation and billed unit price

Keep `customer_quote_pdf` unit-price evidence separate from the internal calculation and from `invoice_unit_price` evidence. Retain the full printed/source precision and verify the extension under the document's stated rounding rule; a rounded extension must not replace the source unit price. A verified customer-quotation price does not establish first sending, accepted version or payment; those need their own state and source if the analysis requires them.

For invoices, use a reviewed original or authoritative issued/posted invoice header and line, not a document-class hint. Preserve original/corrected/reversed event identity, signed billed quantity, price basis, extension, tax, freight, setup and other charge dispositions. Partial-shipment billing is not the whole ordered quantity. An effective net unit amount may be calculated only after explicitly allocating applicable credits and separating charges; label it separately from the printed unit price. Do not divide a header total by a job quantity and call the result its issued unit price.

The document population is not the invoice-event or line denominator. First establish deduplicated header/line identities and multi-invoice PDF boundaries, then report invoice-role/line coverage, unlinked lines and unresolved allocations. Sampled role checks do not supply those population counts.

### Cash applications and settlement

Retain one receipt event and one application event per invoice allocation, with receipt/application IDs, invoice and optional line IDs, customer, currency, application date, amount, posting state, reversals/refunds and unapplied remainder. Retain discounts, credit memos, write-offs and other deductions as distinct noncash events with their own referenced invoice and allocation. A receipt can span invoices and an invoice can receive multiple receipts.

Reconcile, as of an explicit cutoff:

- The signed invoice balance and authoritative debits/credits must equal the amount available for settlement under the declared charge and currency basis.
- That amount must equal net applied cash plus separately classified noncash settlements plus the remaining receivable; reversals and refunds must be included once.
- Receipt applications plus unapplied cash and any supported refund/return dispositions must reconcile to the receipt control total.

Report **recorded applied cash** when only an application ledger is available. Report **confirmed cash settlement** only when the operator-authoritative settlement/clearing source independently supports the receipt's status and the allocations reconcile. A zero balance caused by a credit, deduction, write-off or correction is not proof that the customer paid the invoice. An unapplied receipt is not evidence of payment against a particular job. Keep unknown, part-applied, reversed and disputed states explicit.

### Closed-job realized cost and margin

Require an independently reviewed primary closure event and a complete posting population for the defined job/lot, including final adjustments and reversals through the cutoff. Material, labor, outside processing, setup, scrap/rework, overhead and other included components need source-approved signed-amount semantics, UOM/currency, rate basis and allocation. A zero component requires a supported zero/not-applicable disposition rather than an absent row.

WOBILL.COST must not be summed or multiplied by quantity until its cost basis, lot/unit flag, bill type, posting/reversal state and component scope are approved. Labor collection hours, wage/overhead fields, work-order estimates and shipment costs are separate observations, not automatic additional actuals. In particular, do not double count setup already included in labor or amounts already represented in bills. Deleted physical rows need explicit source dispositions; neither their retention nor normal nondeleted iteration defines the complete closed-job ledger.

For a fully allocated, source-approved revenue and cost scope, report closed-job accrued margin as `net recognized revenue - complete realized cost`, and its rate only for nonzero eligible revenue. Define tax, pass-through freight, credits, discounts, write-offs and overhead inclusion before calculating it. Payment is a separate measure: unpaid accrued revenue must not be reported as collected cash. If needed, report a separately labeled cash-settled contribution result using reconciled, appropriately allocated settled cash; do not silently rename it accrued margin.

Report counts of all linked jobs, closed-event-supported jobs, completely reconciled-cost jobs and margin-eligible jobs, with exclusions for each missing gate. Neither posted-history wins nor positive modeled margin establishes accepted or profitable business outcome.

## 4. Smallest additional source request

Start with one bounded, operator-selected lifecycle cohort anchored to an already retained invoice/job example, chosen without looking at model error or apparent profitability. One complete lifecycle can validate the join contract; it cannot establish general accuracy or financial outcome prevalence. Include a naturally occurring partial shipment, credit/discount or reversal if present, otherwise preserve an explicit source-supported none disposition rather than inventing an example.

Ask for one read-only export/report packet containing:

1. **Original request and accepted versions.** The RFQ/specifications, the actual customer quote/letter version and quantity break, and the primary accepted customer PO/order line with subsequent changes, dates, accepted quantity/UOM/currency, terms and explicit link to quote and native job/lot. The captured sales-order letter pointer cannot fill this gap.
2. **Posted invoice and adjustment lines.** Authoritative invoice header/line identities and job/lot/shipment allocations, signed quantities, unit-price precision, extensions, charge dispositions, posting/issuance states, correction/reversal links and all related credits through the cutoff. Retained PDFs can be source anchors, but their filenames are not keys.
3. **Receipt/application and settlement controls.** Receipt and application IDs, invoice allocations, dates/currency/amounts, discounts and other noncash deductions, reversals/refunds/unapplied balances, authoritative open balances, and the settlement/clearing support required by the chosen cash-confirmation label.
4. **Closure and complete job cost.** The primary closed-job event, the complete material/labor/outside/setup/scrap/overhead posting enumeration with approved unit/lot/rate/allocation meaning, adjustments/reversals and component/grand-total controls. Include the source's treatment of deleted/history records and supported zero components.

For that packet, request the operator's actual table/report map, field definitions, snapshot/cutoff and row-count/amount controls, plus independent source review. The directory names HISTHEAD/HISTLINE/HISTSHIP, RECOPEN/RECHIST/RECAPPLY/reccash and archived work-order families are retrieval candidates only. Ask which authoritative sources the installation uses; do not begin by assuming INVHDR/INVITEM, reccashd or account contains posted customer-invoice and cash-allocation history. A bounded official export may be smaller and more informative than copying every accounting DBF.

If a required component cannot be supplied, name that specific unestablished state and retain it in coverage. Do not call the source absent globally, mark an invoice paid, infer a win from posting, or backfill realized cost from the existing bill-cost column.
