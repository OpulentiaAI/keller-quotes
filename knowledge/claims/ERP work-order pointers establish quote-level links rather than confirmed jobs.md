---
type: claim::au-weave
tldr: Exact native ERP foreign-key equality corroborates quote-level linkage but does not establish acceptance or full quote-item manufacturing identity.
about:
  - "[[private-fabritrak-snapshot]]"
  - "[[source-audit]]"
based_on:
  - "[[Keller original-source audit 2026-10-04]]"
  - "[[Keller historical evidence contract cf1ee17]]"
---

The original-source checks verify 853 WOHEAD candidates across 102 cases and 954 SOMAST/SOLOTS/WOHEAD/WOJOBS chains across 99 cases, with no rejected supplied references in the sealed build.
The [[Keller original-source audit 2026-10-04]] additionally retains 724 quote/customer/part-matching sales-order records across 101 cases, so a sales-order match, physical chain and case count are different grains.

A chain requires matching SOMAST quote/customer/part, nonblank JOBNO across SOMAST/SOLOTS/WOJOBS, matching customer and nonblank WO_NO across lot/work/job, and nonblank LOT equality across lot/job.
The [[Keller historical evidence contract cf1ee17]] labels this observation `QUOTE_LEVEL_ERP_POINTER_ONLY` because quote item, revision, drawing, quantity, acceptance and complete actual cost remain separate checks.
Candidate existence by customer/part is weaker than that chain and never substitutes for it.

The corrected source audit has 84 candidate cases with known nonplaceholder revision equality, only two with revision plus fabrication-quantity equality, and 31 native cases with the limited blank-item/revision/order-quantity conjunction.
Blank and hyphen-placeholder equalities explain the superseded larger counts; they are not evidence of known revision compatibility.
Neither those limited comparisons nor a drawing filename proves manufacturing equivalence or a directly linked independently accepted closed job.
