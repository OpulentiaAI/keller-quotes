---
type: source::au-base-types
tldr: Paired frozen-snapshot replay measurements and retained criterion losses for the scoped-identity candidate.
origin: Private final-paired-summary dated 2026-10-04 and analysis branch described in pull request 26.
---

This is the unchanged 250-case internal-calculation diagnostic, not a live RFQ evaluation, customer-acceptance study or actual-cost test.
The baseline is executable commit `004f2c1`, and the scoped-identity candidate is the separately shipped `929a27f` estimator implementation; the `cf1ee17` full-data follow-up does not change that estimator or rerun this experiment.
The reports retain the same source basis, case identities, original targets, cutoff configuration and historical inclusive ±20% criterion.

| Measurement | Baseline | Candidate |
|---|---:|---:|
| Attempted cases | 250 | 250 |
| Finite priced cases | 231 | 229 |
| Held / no analog | 19 | 21 |
| All-pass cases | 52 | 51 |
| All-case all-pass rate | 20.8% | 20.4% |
| Priced-case median APE | 52.07% | 51.97% |
| Priced-case mean APE | 90.80% | 89.96% |

The comparator exits one because the candidate fails its historical regression gate.
It retains two finite-pricing and extension losses and one ±20% price-pass loss; there are no criterion gains.
The price-population change cannot be used to declare improvement from the aggregate error decrease.
Among 229 finite-price pairs, only two prices change: one APE improves and one worsens.
The paired mean APE change is `+0.0004865833228251358` in fractional-error units, or `+0.04865833228251358` percentage points.
Its paired sample variance is `0.00024985674230740523` in fractional-error-squared units; it uses `n - 1`, not the population variance convention in the workflow reports.
Held and missing prices are not zeros in these numerical statistics.

The source diagnosis retains unsupported identifier-only matching as the cause of the two pricing/extension losses and removal of foreign-namespace exact priority as the mechanism of the remaining price-pass loss.
Customer/part namespaces, normalized aliases, explicit revision/drawing/material conflicts and partial-description provisional analogs are distinct identity conditions, not evidence that cross-customer matching is always invalid or that a provisional analog is manufacturing-equivalent.
No target, old verdict or tolerance was changed to remove those regressions.

| Retained private report | SHA-256 |
|---|---|
| Final paired summary | `7645ef76960f908f3f69b49d3bb92ad56df9aa700b2fa7e61449fd238e596130` |
| Baseline report | `31c07515ae61248f55d2d156aacf3dd43d5e75ea23d3d4a380875e57151cf57c` |
| Candidate report | `651cd3878d7b89432a61fbeb0027537aea09580ab9252a160fe1a446933062f8` |

Private case transitions, target amounts and price proposals remain in the operator evidence bundle, not this graph.
