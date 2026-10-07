---
type: claim::au-weave
tldr: "Versioned line and allocation keys are required to keep prediction error, accepted scope changes, billed unit price, cash settlement and realized margin from being conflated."
about:
  - "[[c-keller-mfg]]"
based_on:
  - "[[Keller retained quote lifecycle source coverage 2026-10-07]]"
  - "[[Keller historical evidence contract cf1ee17]]"
  - "[[Keller Git-pinned experimental reports 68c8201]]"
---

The [[Keller retained quote lifecycle source coverage 2026-10-07]] establishes quote-level native keys and bounded customer-invoice content, while letter-version, invoice/lot allocation, cash application and complete closed-job cost evidence remain separate gaps.
An immutable quote-stage version must retain its selected source basis, customer/line identity, revision/drawing, quantity tier, UOM, currency and terms alongside the model prediction and evidence cutoff.
Without that same-scope target, invoice-versus-quote differences may reflect a changed order or partial shipment rather than prediction error.

An accepted-order line should explicitly reference the quote/letter version and carry change events; native JOBNO and WO_NO/LOT then support a separately reviewed manufacturing allocation.
An invoice event needs its own header and line identity, signed billed quantity, full source unit price, extensions and tax/freight/credit dispositions.
Receipt and credit applications must retain their own event IDs, reversals, amount bases and invoice allocations so applied cash is not counted as billed revenue or a discount as cash.

Report same-scope price error, changed-scope deltas, role-verified billed unit price, reconciled cash applications and complete-job margin as separate measures with separate eligible and all-case denominators.
Unknown states remain unknown: posted-history won labels are not confirmed wins, an invoice is not paid-invoice proof, and unreconciled cost fields are not realized cost.
The smallest additional evidence request is one operator-selected, bounded quote/order/job cohort with accepted versions and changes, posted invoice lines, receipt/credit applications and complete closure/posting controls; selection must not depend on model errors.
