---
type: claim::au-weave
tldr: "Original manufacturing bytes contain cost and labor-related observations, but component meaning, posting scope, closure and completeness remain necessary before realized margin can be calculated."
about:
  - "[[c-keller-mfg]]"
based_on:
  - "[[Keller retained quote lifecycle source coverage 2026-10-07]]"
  - "[[Keller original-source audit 2026-10-04]]"
  - "[[Keller historical evidence contract cf1ee17]]"
---

The captured native sources include work-order headers, jobs, operations, shipments, labor collection, bills and BOM rows.
The [[Keller retained quote lifecycle source coverage 2026-10-07]] verifies all 1,981 linked bill and 13 linked BOM references in the bounded 250-case audit, so some actual manufacturing-source data is physically present.
The same audit establishes zero complete actual-cost ledgers, rather than proving that the business has no closed or paid jobs.

Physical header counts are not active posting counts: WOSEQ has 185,067 header records and 4,040 nondeleted records; WOBOM has 52,249 header records and 1,149 nondeleted records.
The retained deleted bytes need explicit historical and accounting dispositions, while missing business memo companions prevent treating the DBF capture as complete narrative evidence.
Neither blindly including tombstones nor silently discarding them establishes the complete cost population of a closed job.

WOBILL.COST does not by itself establish unit versus lot basis, estimate versus posted actual, reversals, full component inclusion or labor/setup allocation.
Realized margin requires an authoritative closed-job event and reconciled material, labor, outside, setup, scrap and overhead postings under explicit quantity, UOM, currency and allocation rules.
The [[Keller historical evidence contract cf1ee17]] retains independent source review and explicit zero-component dispositions as requirements, not assumptions supplied by field names.
