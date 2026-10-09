---
type: map.overview::au-weave
tldr: "Dated Steve provider research, non-analog costing decisions and isolated retrieval experiments; implementation, verification and unresolved obligations stay separate."
about:
  - "[[c-keller-mfg]]"
---

## Evidence and decisions

[[Steve user steel-provider research 2026-10-09]] preserves Jeremy's reference and shortlist, linked to [[Steve steel-provider documentation review 2026-10-09]]. Typed provider records: [[Fastmarkets]], [[MetalMiner]], [[CRU]], [[Platts]]. [[Should-cost is a supported non-analog alternative not a benchmark substitution]] records the intended alternative and the boundary around uncommitted work.

## Implementation versus access

- Original Steve worktree/PR #28: uncommitted fallback reconciliation, worksheet-derived `should_cost`, and bounded `keller_market` adapter. No production activation or merge. Fastmarkets bearer and licensing still needed; MetalMiner OAuth/premium entitlement not connected.
- Bounded market batch: max three public-selector supplier searches, three results each; one BLS series; one Fastmarkets call for three fixed symbols. Five HTTP attempts, no redirect/retry/page loops, 8-second socket timeout, 256-KiB responses, 45-second child deadline. Default off. External RFQ/customer/part text is not accepted as a search argument.
- Separate WonderSearch worktree: branch `devin/1791535727-steve-wondersearch`, SDK pinned to 0.2.0, isolated private run artifacts and default-off adapter. Independent preflight/implementation/evaluation stages are running; no retrieval gains claimed here. Preserve the unchanged frozen cohort, scope and $5/1-GB constraints. That lane must not change pricing policy or defaults.

## Measurement

The earlier frozen customer-PDF diagnostic remains 45/250 all-pass, 220 priced and 30 held, with three gains and three losses and a failed median-APE regression gate. It is development historical replay, not live-cost accuracy or untouched confirmation. See `docs/steve-development-diagnostic.md` and its pinned private experiment plan/records. The >90% end-to-end goal is unproven.

Knowledge records are operator-only, not automatically included in blinded worker contexts. Keep source documents, target labels, credentials, price rows and per-case failure diagnoses in approved private storage. Public knowledge retains source links, code/test identity, hashes, aggregate counts and explicit unknowns.
