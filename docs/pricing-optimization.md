# Measured pricing policy proposal

This proposal changes analog selection and weighting, not the source register, quoted outcomes, evaluation criteria, or the order approval boundary. It is separate from output-preserving retrieval speedups so those can be reviewed independently.

**Experimental, not recommended as the default yet:** unit-error metrics improve, but the diagnostic holdout within-20% count and the supplemental sample's aggregate signed-dollar error regress. Business acceptance criteria for underquoting need to be decided before adoption; passing the current unit-metric gate alone is insufficient.

These measurements describe the original pricing-policy replay, before the newer top-N admission pipeline. In the combined estimator, exact preference operates on retrieved, cutoff-safe candidates before ranking. When no exact match is priceable, unusable exact rows cannot consume the bounded screening budget for other evidence. Only screened and admitted candidates can feed strategy, pricing, references, or quantity-range warnings. The historical metrics below do not measure that combined pipeline and cannot establish its accuracy; run a separately scoped, matched evaluation before making such a claim.

## What the data supports

The baseline development partition has 203 cases, of which 191 are priced. Only seven have usable exact-part history after source exclusion and the quote-time cutoff. Most requests are therefore priced from other parts rather than a previous price for the requested part. Manufacturing dimensions, operation times, and current material/labor costs are not supplied by this evaluation; a historical description or similar part number does not establish equivalent manufacturing cost.

Retrieval adds matching/customer/material/outcome signals, caps their sum at 1.0, and breaks score ties by newest quote date. In the development reconstruction, 59 of 1,567 returned candidates hit that cap; 50 of those were not exact matches. A newer saturated fuzzy candidate precedes an exact match in two of the seven exact-match cases. Those counts identify a concrete selection problem, not proof that all fuzzy matches are bad.

Old evidence is a risk signal, but "use newer prices" was not an effective general correction in the experiment. This replay estimates historical quote-time prices, not today's prices. There is no inflation series or authorized current-cost feed, and the tiny pre-2000 slice cannot support a blanket decade-based uplift.

## Selection protocol and rejected alternatives

Policy selection used only the existing **203-case development partition**. The 47-case grouped holdout has already been inspected in prior work and remains diagnostic, not blind. Two bounded batches evaluated general policies rather than tuning individual quote cases:

| Development policy | Priced / 203 | Median APE | Within ±20%, count | Mean APE |
|---|---:|---:|---:|---:|
| Existing weighted median | 191 | 54.18% | 42 | 80.05% |
| Latest analog for every request | 191 | 69.03% | 35 | 122.87% |
| Two-year rather than eight-year recency decay | 191 | 54.27% | 38 | 101.22% |
| Prefer priceable exact matches | 191 | 53.01% | 46 | 78.76% |
| Prefer same-customer exact matches | 191 | 53.01% | 46 | 78.76% |
| Latest analog after exact gating, including fallback requests | 191 | 64.95% | 38 | 121.96% |
| Latest only when an exact match exists | 191 | 53.01% | 46 | 78.76% |
| Exact first, otherwise same-customer candidate pool | 191 | 49.48% | 44 | 79.26% |
| Quantity-proximity weight alone | 191 | 53.01% | 43 | 68.73% |
| **Exact preference + quantity-proximity weight** | **191** | **52.30%** | **47** | **67.33%** |

The combined policy was selected for the highest within-20% count with unchanged coverage and lower median/mean error. Selection was frozen before scoring a supplemental 500-case set. No new policy was selected or tuned after those validation results.

The original implementation prefers usable normalized exact-part candidates **among the retrieved candidates**, before model ranking/screening and pricing. If no priceable exact candidate is returned, the original experiment keeps the existing pool; the combined pipeline instead removes unusable exact rows to avoid exhausting its screening budget. Neither reintroduces a source quote, a future/revised quote, or otherwise excluded history. The experiment also searched the broader scored pool; none of the 750 evaluation requests lost all its available exact matches to the existing 12-candidate limit. That observation is not a guarantee about every possible future request.

Pricing multiplies each existing candidate weight by:

```text
1 / (1 + min(abs(log(historical_quantity) - log(requested_quantity))))
```

The minimum is over that candidate's finite positive quantity/price breaks. A matching quantity keeps its weight; increasingly distant quantities lose influence smoothly. The logarithm difference avoids overflow from dividing extreme finite quantities. Existing interpolation, recency decay, customer/won/model weights, and quote-time filters remain in place. A warning calls out requests outside every usable analog's quantity range; the warning is not a fabricated confidence calibration or an automatic order rejection.

## Validation and the tradeoff

| Set | Priced, before → candidate | Median APE | Within ±20%, count | Mean APE |
|---|---:|---:|---:|---:|
| Fixed 250 cases | 237 → 237 | 53.01% → 50.31% | 55 → 58 | 87.28% → 73.73% |
| Development portion, 203 cases | 191 → 191 | 54.18% → 52.30% | 42 → 47 | 80.05% → 67.33% |
| Diagnostic holdout, 47 cases | 46 → 46 | 50.34% → 41.20% | **13 → 11** | 117.28% → 100.32% |
| Supplemental 500 distinct part families | 481 → 481 | 55.54% → 51.81% | 99 → 105 | 137.49% → 126.33% |

**The held-out diagnostic within-20% count regresses by two even though its median and mean improve.** This is a visible review decision, not a clean win on every metric. The whole-set comparison passes the aggregate coverage/median/all-pass regression gate; the same acceptance rule applied only to that 47-case slice would fail. No thresholds were weakened to hide it.

Quantity-weighted dollar exposure tells another important story. On the same priced cases, aggregate predicted-minus-historical extended dollars change as follows:

| Set | Baseline signed error | Candidate signed error |
|---|---:|---:|
| Fixed 250 cases (237 priced pairs) | +$38,949.47 | −$1,238.63 |
| Supplemental 500 cases (481 priced pairs) | −$226,579.84 | **−$336,122.60** |

The supplemental candidate predicts $109,542.76 less in aggregate, increasing underquoting relative to the historical quoted totals even while typical unit-price error improves. This is a sample diagnostic in historical nominal dollars, not realized revenue or margin loss; actual production costs and customer acceptance are unavailable. It is nevertheless a reason to leave the pricing policy experimental rather than optimize median APE in isolation. The existing regression gate reports this dollar metric but does not gate on it.

The supplemental set uses the same frozen register, not a new source extract or real-world deployment trial. Before policy selection it was generated deterministically as follows:

1. Exclude normalized part numbers present in the fixed 250-case file, and require a nonempty normalized part number and a dated source quote.
2. Within each register quote/item group, choose the middle quantity break among finite positive quantities/prices, preserving the loader's quantity ordering.
3. Hash `keller-validation-v1\n<quote_no>|<item_no>@<quantity>` with SHA-256, sort by that hash, and keep the first case for each normalized part number.
4. Take the first 500 distinct families and serialize in case-ID order using the input fields `part_no`, `description`, `quantity`, and `customer_id`, plus actual price/quantity/date/status for scoring only.

Provenance:

- Starting code: merged `main` commit `0411e4a`.
- Register SHA-256: `6ed19d0cf550f3e65f420b676bbc4354c8dfaf05912d1f5f4edefb4bc8b24cfe`.
- Fixed evalset SHA-256: `6fb53d2600a2fa46715c869e1f72f067c92be688b245e3146c3e1a9f7e9a9e3f`.
- Supplemental JSONL SHA-256: `02cd1c1627fd735a8c2207c06819369636db39b8b5fd6dfb811dcb312b24cb8e`.

The fixed sample overweights won/recent quotes; the supplemental sample filters for valid prices and distinct part families. Neither estimates production prevalence. Both are cutoff-aware frozen-snapshot replays, not true historical backtests: unversioned edits may survive in earlier records. `open` still includes silent losses and expired quotes; it is not an explicit lost outcome.

## Limits and next evidence needed

Median errors remain large and within-20% performance remains low. Confidence is a heuristic evidence score, not a calibrated probability of an accurate price. Historical analogs cannot replace current cost inputs, drawing/geometry review, or a named pricing reviewer. The structured cost-build-up order path remains the appropriate explicit route when reliable current costs are supplied.

Further pricing experiments should use a new predeclared validation set or prospective reviewed RFQs rather than repeatedly selecting against these now-observed validation results. Customer affinity is a plausible next hypothesis, but a same-customer association is not evidence for a hard customer filter. Material/drawing/operation enrichment requires authorized source data; this change makes no source re-extraction, live database write, or paid model call.
