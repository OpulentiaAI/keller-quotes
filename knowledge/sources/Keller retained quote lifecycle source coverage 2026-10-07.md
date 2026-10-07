---
type: source::au-base-types
tldr: "Retained native quote-to-job pointers and original invoice content are available, but letter-version, invoice-allocation, cash-settlement and complete realized-cost evidence remain distinct gaps."
about:
  - "[[c-keller-mfg]]"
origin: Read-only retained-source inspection and explicitly selected document-corpus observations dated 2026-10-07.
based_on:
  - "[[Keller Git delivery and private artifact access 2026-10-07]]"
  - "[[Keller original-source audit 2026-10-04]]"
  - "[[Keller historical evidence contract cf1ee17]]"
---

This follow-up distinguishes captured original bytes, stored field populations, document annotations and business-event authority.
The [[Keller Git delivery and private artifact access 2026-10-07]] supplies authenticated recovery of the retained archive, not proof that every source needed for a completed quote lifecycle was supplied.
Exact original digests, recovery aliases, physical-record references and private representative content are confined to the operator verification receipt.
No production source was changed, and this observation does not activate knowledge or authorize a customer quote.

## Document population and source roles

The selected warehouse corpus contains 39,975 PDF records, 75,096 extracted pages and 42,873 verified customer-quotation quantity breaks from 7,845 price-source PDFs.
All 39,975 recovered original PDFs matched their retained catalog sizes and whole-file digests in this audit; the original family includes one zero-byte file.
All 42,873 verified price rows join to documents annotated as quotations; this table is not an invoice-line or payment register.
The current document annotations are:

| Content annotation | PDF records / 39,975 | Extracted pages / 75,096 |
|---|---:|---:|
| Invoice | 12,511 | 36,775 |
| Quotation | 14,724 | 14,743 |
| Supplier purchase order | 11,316 | 18,462 |
| Packing slip | 987 | 1,611 |
| Certificate | 288 | 301 |
| Unknown | 149 | 3,204 |

These are document and extraction grains, not counts of unique bills, accepted orders, receipts or closed jobs.
The 11,406 invoice-filename hints comprise 10,474 invoice annotations, 860 packing-slip annotations and 72 unknown annotations.
The current invoice count also includes 2,035 optional-filename records and two other-filename records.
An older retained classification report has 1,496 invoice annotations in the same 39,975-document population; the current count is a different classification observation, not evidence that 11,015 new bills were issued or newly supplied.
Poppler text is present for 39,960 records, 14 are blank and one failed; a failed or blank extraction is not evidence of a missing business event.

Eight original first pages were checked against newly extracted, hash-matching source text: seven have customer-invoice-form content and one is an invoice journal report.
One invoice form was also reviewed visually against a fresh rendering of its original PDF; its issuer footer identifies the manufacturer, while a different organization is the addressed recipient.
It contains invoice and shipped-date labels, payment terms, a purchase-order reference, quantity, job number, part, revision, unit price, extension and total.
That is evidence of outbound billing content, not authenticated sending, bank settlement, accepted scope or final job closure.
One sampled two-page PDF contains two different printed invoice numbers, and the journal report has six pages; PDF count therefore cannot serve as an invoice-event denominator.
These deliberately selected role checks are not a random survey of all 12,511 invoice annotations.

A bounded heading search found no cash-receipt or credit-memo heading matches, and found 11 accounts-receivable heading matches in six documents.
All six matched documents are retained software documentation, not customer receivable ledgers.
The documentation explains invoice posting, aged receivables, cash applications, unapplied payments, deductions and cash journals; it does not prove this installation's accounting configuration or any actual payment.
The narrow heading search does not prove that incidental receipt, credit or adjustment content is absent elsewhere in the corpus.

## Native quote, letter, item and job pointers

The two retained native source sets contain ten business DBFs, three dictionary DBCs and three dictionary memo companions: 16 original files in total.
Their schema and nondeleted field populations support the following distinctions:

| Stored field observation | Populated active records / active-record denominator |
|---|---:|
| SOMAST.QUOTE_NO | 94,153 / 99,920 |
| SOMAST.JOBNO | 99,920 / 99,920 |
| SOMAST.QUOTLETT | 0 / 99,920 |
| SOMAST.UOM | 1 / 99,920 |
| SOMAST.CFACTOR | 0 / 99,920 |
| SOMAST.CURRENCY_P | 0 / 99,920 |
| SOLOTS.JOBNO | 156,319 / 156,321 |
| SOLOTS.WO_NO | 144,642 / 156,321 |
| SOLOTS.LOT | 156,315 / 156,321 |
| SOLOTS.ITEM_NO | 3 / 156,321 |

QUOTLETT.QUOTLETTER joins a letter header to QUOTLINE.QUOTLETTER; the letter-local QUOTLINE.ITEM joins quantity breaks on QUOTLEIT.(QUOTLETTER, ITEM).
QUOTLINE.QUOTE_NO provides the calculation-quote pointer.
SOMAST.QUOTE_NO, COMP_ID and PART_NO support a quote/customer/part comparison, then SOMAST.JOBNO links sales lots and work-order job references.
A retained four-table chain requires nonblank JOBNO equality across SOMAST, SOLOTS and WOJOBS; customer equality across SOMAST, SOLOTS and WOHEAD; nonblank WO_NO equality across SOLOTS, WOHEAD and WOJOBS; matching part in SOMAST and WOHEAD; and nonblank SOLOTS.LOT = WOJOBS.LOT.

SOMAST.QUOTLETT is a schema-level opportunity, not a usable letter-version pointer in these captured active records, because every value is blank.
QUOTLINE.ITEM, QUOTEN.ITEM_NO and SOLOTS.ITEM_NO are different native fields and must not be equated merely because their names contain item.
Revision, drawing, quantity tier, UOM, currency, accepted change and letter-version identity remain separate checks.
SOLOTS.INVOICE_D supplies a stored date-looking field, not an invoice identifier, invoice line, receipt or payment allocation.

The superseding 250-case audit retains 724 matching sales-order records across 101 cases and 954 four-table pointer chains across 99 cases.
Every retained chain's four physical records and foreign-key equalities were rechecked: 3,816 physical-record checks, without promoting the result beyond quote-level pointer evidence.
The corrected audit's stronger blank-item/known-revision/order-quantity conjunction covers 31 / 250 cases and does not resolve drawing, acceptance or full manufacturing equivalence.
One visually reviewed invoice's printed job, part and revision match one captured sales-order record, with one sales-lot and one work-order-job key match.
This is one illustrative key observation, not a validated population invoice join, recipient-ID mapping or lot/line allocation.

## Financial names versus captured data

The original directory inventory has 978 rows: 977 file entries and one folder entry, including 265 DBF filenames.
INVHDR, INVITEM, reccash, reccashd and account are named there, but none of their DBF bytes or field schemas is present in the audited recovered sources.
Their five-table capture count is 0 / 5; their actual row counts, purposes and population completeness remain unknown.
Displayed sizes, companion-file names and filenames do not establish empty tables, current accounting use or a confirmed invoice-to-payment join.

The directory also names historical invoice/history candidates, receivable/open/history/application candidates and archived work-order candidates, without supplying those table bytes in this archive.
The captured ORDERS, PURCHASE and WORKORDR dictionaries describe other source families; they are not a recovered accounting dictionary for the five named financial tables.
The current warehouse public schema contains quotation, generated-estimate and document-evidence relations, not curated invoice-line, cash-application or credit-allocation relations.
Captured invoice PDFs and the journal report are real evidence, but a normalized authoritative invoice/credit/application dataset has not been established by this audit.

## Actual-cost support and unresolved completeness

Captured manufacturing sources include WOHEAD, WOJOBS, WOSEQ, WOSHIP, WOCOLL, WOBILL and WOBOM.
They contain cost-, hours-, quantity-, wage-, overhead- and estimate-looking fields, not an independently approved closed-job cost reconciliation.
The 250-case audit has 1,981 linked WOBILL rows and 13 linked WOBOM rows; all 1,994 retained component references were rechecked against original physical records.
It establishes zero complete actual-cost ledgers and zero independently confirmed acceptances in that bounded case population, not zero paid or closed jobs in the business.

Physical DBF headers and nondeleted records differ substantially in some sources: WOSEQ has 185,067 header records but 4,040 active records, and WOBOM has 52,249 header records but 1,149 active records.
Deleted physical records remain in the captured bytes; their historical or accounting disposition requires an explicit enumeration contract rather than silently summing or discarding them as realized costs.
Several native business DBFs reference memo fields whose memo companions were not supplied in those two native source sets.
The older vendor-quote memo companion is separately retained, but that does not supply missing work-order or sales-order memo content.

WOBILL.COST alone cannot establish whether an amount is per unit or per lot, estimated or posted, reversed or final, or inclusive of labor, outside processing, setup, scrap and overhead.
The [[Keller historical evidence contract cf1ee17]] still requires authoritative acceptance and closure, complete posting enumeration, component and amount reconciliation, compatible identity/quantity/UOM/currency, source-supported zero dispositions and independent source review.
The available next step is a bounded, operator-selected lifecycle export with invoice-line and lot allocation, receipt/credit application and complete closed-job postings, not a price-error score inferred from invoice filenames or a sum of cost-looking fields.
