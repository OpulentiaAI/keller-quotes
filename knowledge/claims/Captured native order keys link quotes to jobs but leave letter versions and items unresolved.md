---
type: claim::au-weave
tldr: "Exact stored quote-to-job pointers are available, but the captured letter pointer is entirely blank and native item fields do not establish accepted line or version identity."
about:
  - "[[c-keller-mfg]]"
based_on:
  - "[[Keller retained quote lifecycle source coverage 2026-10-07]]"
  - "[[Keller original-source audit 2026-10-04]]"
  - "[[Keller historical evidence contract cf1ee17]]"
---

The [[Keller retained quote lifecycle source coverage 2026-10-07]] rechecks 954 SOMAST/SOLOTS/WOHEAD/WOJOBS chains across 99 / 250 assessed cases using original physical records and nonblank job, work-order and lot keys.
SOMAST.QUOTE_NO is populated in 94,153 / 99,920 active records, so exact quote/customer/part comparison is supported rather than inferred from document filenames.
This establishes quote-level native pointer evidence, not customer acceptance or complete manufacturing equivalence.

SOMAST.QUOTLETT exists in the captured schema but is blank in all 99,920 active records.
The quote-letter header and its letter-local line/quantity-break fields can be linked within the quotation sources, but the captured sales orders do not identify which issued letter version was accepted.
QUOTLINE.ITEM, QUOTEN.ITEM_NO and SOLOTS.ITEM_NO are different fields; the last is populated in only 3 / 156,321 active sales-lot records and cannot supply a general letter-line mapping.

A lifecycle join therefore needs an explicit accepted quote/letter version and line allocation in addition to the native quote/job/work-order keys.
Unknown drawing, revision, quantity tier, UOM and currency cannot be treated as equality, and stored confirmation, closure or invoice-date fields cannot replace primary business-event evidence.
