---
type: claim::au-weave
tldr: "Physical missing values, explicit numeric zeros and synthetic join placeholders must retain their separate meanings."
about:
  - "[[c-keller-mfg]]"
based_on:
  - "[[Keller retained physical source and integrity audits]]"
  - "[[Keller Git-pinned experimental reports 68c8201]]"
---

Legacy blank fields, explicit zero values and placeholder breaks are different source states.
The original DBF/export reconciliation in [[Keller retained physical source and integrity audits]] preserves 2,210 placeholder rows with no usable break price, rather than treating them as free quotations.
The physical manufacturing profile distinguishes blank finished-dimension bytes on 28,999 active quote heads from explicit zeros on 11,112 of the same 40,111-head population; neither population provides positive finished dimensions.
It also finds no positive SUTIME or RUNTIME in the 299,882 active quote-operation rows while retaining operation rates, variables and formula references.
Those zero or missing result fields do not establish that the physical work takes no time or incurs no cost.
The separate internal-order contract in [[Keller Git-pinned experimental reports 68c8201]] allows shipping or tax zero only when explicitly supplied; absent or null charges remain blockers, not automatic zeros.
Source-state semantics and order completeness must not be conflated.

