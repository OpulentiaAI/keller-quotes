---
type: claim::au-weave
tldr: "Safe arithmetic and complete formula lookup coverage still lack populated independent operation results and verified units."
about:
  - "[[c-keller-mfg]]"
based_on:
  - "[[Keller retained physical source and integrity audits]]"
  - "[[Keller Git-pinned experimental reports 68c8201]]"
---

Resolved formula references and evaluable arithmetic do not independently validate manufacturing cost aggregation.
The physical-source profile in [[Keller retained physical source and integrity audits]] resolves every observed nonblank active operation-formula reference to one of 13 retained definitions.
It separately distinguishes numeric inputs, positive inputs, missing inputs and zero-denominator risks, while finding no positive stored setup/run time or per-operation extended-cost result to validate the aggregation.
Some literal formula labels and stored arithmetic have unresolved unit interpretations; unused lookup formulas do not create a need to invent missing tables for the observed references.
Material and operation rate evidence therefore does exist, but arithmetic-only evaluation is not proof of complete or current costs.
The [[Keller Git-pinned experimental reports 68c8201]] keeps that limitation separate from historical quoted prices and supported current-cost inputs.

