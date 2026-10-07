---
type: claim::au-weave
tldr: "Fixed inputs and source-bound replay locate the observed numerical behavior in screening and interpolation rather than a model switch."
about:
  - "[[c-keller-mfg]]"
based_on:
  - "[[Keller retained offline backend learning evidence]]"
  - "[[Keller Git-pinned experimental reports 68c8201]]"
---

The recorded automatic historical-pricing backend constructed an offline JevClient independently of the worker model.
The source-bound replay in [[Keller retained offline backend learning evidence]] reproduced all five serialized v4 line payloads with the original requests, scoped registers and pricing source.
The backend used score-based admission and median_won interpolation over admitted historical curves; the strategy name did not establish verified wins or physical equivalence.
No recorded worker authored a current-cost or explicit-price override for those proposals.
A caller-model switch therefore did not change this fixed backend by itself, although changed submitted attributes or admitted evidence could change its output.
The independent model-review acceptance and operator-only historical application recorded in [[Keller Git-pinned experimental reports 68c8201]] did not demonstrate a behavioral accuracy gain.

