---
type: claim::au-weave
tldr: "Original image and text checks identify customer-billing content in retained invoice samples, without establishing sending, accepted scope, payment or complete-job settlement."
about:
  - "[[c-keller-mfg]]"
based_on:
  - "[[Keller retained quote lifecycle source coverage 2026-10-07]]"
  - "[[Keller Git delivery and private artifact access 2026-10-07]]"
---

The [[Keller retained quote lifecycle source coverage 2026-10-07]] verifies seven original invoice-form first pages and one invoice-journal first page against fresh source text.
One original invoice image was also checked against a fresh, pixel-identical rendering: the manufacturer is printed as issuer, a separate organization is addressed as recipient, and the line contains quantity, job, part, revision, unit price and extension.
Those observed roles establish customer-billing content for the reviewed examples rather than relying on an invoice filename or classifier.

One reviewed invoice's printed job, part and revision match one native sales-order record, with one matching sales-lot and work-order-job key.
That bounded observation supplies a candidate bridge through printed Job # to native JOBNO; it does not validate invoice identifiers, all document lines, recipient IDs, lots, partial shipments or the entire invoice population.

Terms, shipped-date labels, totals and an issuer footer do not show a receipt, allocation, cleared payment, authenticated sending or customer acceptance.
Invoice-journal debits and credits are accounting-posting content, not proof of a credit memo or paid invoice.
Business settlement must remain unknown until receipt and credit applications are independently reconciled to the correct invoice events.
