# Closing the quote-to-payment evidence gap

The initial estimate, customer-issued quote, ordered scope, invoiced amount, allocated cash and closed-job cost are different observations. Measure changes only after joining the same customer, component, revision, quantity basis and line/version identity. A price difference across changed scope is not automatically an estimate error.

## What the retained originals establish

The [[Keller retained quote lifecycle source coverage 2026-10-07]] and [[map - Keller quote lifecycle gap closure]] preserve the completed read-only source audit. All 954 retained quote-to-job/work-order chains across 99 / 250 assessed cases were rechecked against 3,816 physical records. But the captured sales-order letter pointer is blank in all 99,920 active records, and the sales-lot item field is populated in only 3 / 156,321 records. These keys do not identify the accepted letter version or supply a general quote-line allocation.

The originals include invoice-form PDFs and a journal, so the gap is **not** an absence of invoices. The 12,511 invoice-annotated PDFs include reports and multi-invoice files, while invoice filenames also identify 860 packing slips; these counts are not unique issued bills or payments. Original invoice image/text checks support outbound customer-billing roles for reviewed samples. A sampled printed job/part/revision match supplies a candidate native job bridge, not a validated population invoice-line join.

INVHDR, INVITEM, reccash, reccashd and account are directory names only: zero of those five table files or their field schemas are captured, and their actual row counts are unknown. The 1,981 linked bill and 13 linked BOM rows are physically supported cost-related observations, but the bounded 250-case audit establishes zero complete actual-cost ledgers. Payment and realized margin remain unestablished rather than being imputed from invoice presence, posted-history labels or WOBILL.COST. The [source-coverage artifact](../artifacts/keller-quote-lifecycle-coverage-2026-10-07.json) retains the exact denominators and limitations.

## Evidence needed at each stage

| Stage | Required identity and evidence | What it does not establish |
|---|---|---|
| Client request and initial estimate | Original RFQ and drawing/specification revision, stable requested line IDs, quantity/UOM, timestamped initial estimate and its then-available evidence | A current unversioned row does not reconstruct the original decision. |
| Quote revisions and customer issuance | Separate version IDs, line-level changes, printed quantities and unit precision, first-issuance evidence and authorized terms | Numeric reconciliation or an early metadata date does not prove that version was issued then. |
| Accepted order and work order | Exact stored quote/letter/item links plus independently checked customer, part, revision, quantity and UOM | A quote-level ERP pointer does not confirm a component-level accepted order. |
| Customer invoice and credits | Verified issuer/recipient and invoice purpose; job/order/line keys, shipment quantity, amount basis and credit/reversal links | An invoice is not cash settlement; a supplier invoice or template is not a customer sale. |
| Cash settlement | Receipt, allocation and reversal rows linked to the actual invoice and currency, with balances and dates reconciled | A deposit flag, payment terms, shipped status or posted-history label is not proof of paid-in-full. |
| Closed-job actual costs | Closure state plus reconciled material, labor, machine, subcontract, scrap/rework and overhead postings at their actual grains | A populated historical cost field or linked bill row does not establish complete realized cost. |

The [[map - Keller operator findings]] preserves the already established source limitations. The original source and diagnostic bytes remain recoverable through [[Keller Git delivery and private artifact access 2026-10-07]]. The document index preserves all original extraction failures instead of silently dropping them.

## Join and measurement contract

The [versioned lifecycle measurement contract](quote-lifecycle-measurement-contract.md) specifies stage, line and version keys; many-to-many allocations; source-approved accounting semantics; and the smallest bounded additional source request.

Retain the chain `request → estimate version → quote version/line → order line → work order → invoice line → cash allocation`, with credit/reversal and cost-posting branches. Record source hash, source row/page, declared key namespace, date semantics and verification status at each edge. One-to-many shipments, invoices, receipts and cost postings must stay one-to-many; do not flatten them into a duplicated line total. Preserve an unresolved edge as unknown, not zero or false absence.

Evaluate the initial estimate against the final **comparable** issued scope and unit basis. Separately explain revision, quantity, material, finish, routing, lead-time and commercial changes. Reconcile ordered/invoiced/credited/paid totals at their proper grains, then calculate realized margin only where settlement and complete closed-job costs are established. Freeze the timestamped initial evidence before using any later invoice, payment or cost as an operator-only evaluation target.

Current historical replay and the synthetic order benchmark are not this lifecycle population. Keep holds, unlinked lines, invalid records and unknown settlement/cost states in coverage accounting, and report the comparable-price, confirmed-settlement and complete-cost denominators separately. Do not tune one global multiplier against mixed stages or retroactively expose final outcomes to quote workers.

## Bounded next source assessment

Start with source-role and exact-key verification on a small versioned line cohort. First determine which invoice, receipt/allocation, credit/reversal and cost records are physically retained and readable rather than only present in a directory inventory or dictionary. Request only the missing originals and source-owner semantic review needed for that cohort. Expand after the joins and monetary reconciliation pass; do not infer payment or realized costs from field names.

This is an operator evidence-remediation contract. It changes no estimator weights, activates no learning rule, writes no production source and authorizes no customer release.
