---
type: claim::au-weave
tldr: "The bounded rounding effect was far smaller than the retained numerical errors on the five reproduced proposals."
about:
  - "[[c-keller-mfg]]"
based_on:
  - "[[Keller retained offline backend learning evidence]]"
  - "[[Keller Git-pinned experimental reports 68c8201]]"
---

Four-decimal unit rounding was too small to explain the observed v4 historical proposal misses.
The five-case source-bound diagnosis in [[Keller retained offline backend learning evidence]] bounds each recorded rounding effect below 0.0014 percentage points, while reproducing the complete line payloads offline.
The [[Keller Git-pinned experimental reports 68c8201]] also separates interpolation and source selection from cent-level extension arithmetic.
That bounded comparison rules out rounding as the material cause for these observations, not every possible unit or display defect.
The exact target derivations remained unavailable, so ruling out rounding did not establish a particular cost adjustment.

