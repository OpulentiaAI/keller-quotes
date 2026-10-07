---
type: claim::au-weave
tldr: "The invoice-class population is a document annotation denominator, and reviewed examples show why it cannot be used as an invoice, issuance or payment count."
about:
  - "[[c-keller-mfg]]"
based_on:
  - "[[Keller retained quote lifecycle source coverage 2026-10-07]]"
  - "[[Keller retained physical source and integrity audits]]"
---

The selected corpus has 12,511 invoice annotations among 39,975 retained PDFs, representing 36,775 / 75,096 extracted pages.
The [[Keller retained quote lifecycle source coverage 2026-10-07]] separates that current annotation from an older retained 1,496-invoice classification in the same PDF population; a classification difference does not establish newly issued bills.

Of 11,406 invoice-filename hints, 860 are annotated as packing slips and 72 remain unknown.
A reviewed two-page PDF contains two different printed invoice numbers, and a separately reviewed invoice journal is included in the invoice annotation class.
So a document may contain multiple billing events or a report rather than one customer invoice, and invoice filenames can identify noninvoice content.

All 42,873 normalized verified price breaks belong to 7,845 quotation PDFs; they are not a normalized invoice-unit-price dataset.
Population invoice identifiers, line counts, issuance and cash settlement require their own role-verified, deduplicated source and denominators instead of reusing the document-class or quotation-price counts.
