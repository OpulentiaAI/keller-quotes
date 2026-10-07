---
type: claim::au-weave
tldr: Calculation coverage is complete in the assessed historical set, but customer amounts and native quote-to-job pointers cover different partial populations.
about:
  - "[[frozen-internal-register]]"
  - "[[source-audit]]"
based_on:
  - "[[Keller original-source audit 2026-10-04]]"
---

The 250-case diagnostic has complete original-calculation coverage, recorded customer amounts for 107 cases and quote-level ERP pointers for 99 cases.
The [[Keller original-source audit 2026-10-04]] grounds those counts in a sealed source reconstruction and keeps them distinct from the full 179,608-break calculation register.
Only 40 cases have both recorded customer amounts and ERP pointers, while 67 have only recorded amounts, 59 only ERP pointers and 84 neither of those two sources.
Every group still has its original internal calculation; none is a lost-order or live-accuracy population.

Target-comparable customer amounts cover 105 cases, with 39 of those also having ERP pointers.
Work-order candidates cover 102 cases, including all 99 pointer cases and three candidate-only cases.
The source-file inventory counts configurations and derivative proofs as well as originals, so it must not be read as a number of accepted business events.
The [[Recorded customer amounts do not establish issued or accepted quotes]] and [[ERP work-order pointers establish quote-level links rather than confirmed jobs]] explain why this overlap is still not full historical evidence.
