# Blinded historical quote workflow: price variance

**Integrity correction:** a later [worker-context audit](blinded-context-integrity.md) found prior aggregate outcomes in all 18 traces. The arithmetic below remains unchanged and useful diagnostically, but none of these cohorts is cleanly blinded to prior results. Original alias/coverage exclusions are not a statement of overall blinding validity.

This is a numerical reconstruction of the **18 existing workflow attempts on six RFQs**, not a new model-driven evaluation. Their original scores and the inclusive ±20% V3 tolerance are unchanged; the full all-ten-criterion gate remains **0/18**. The 27 actual quote-tool calls comprise 18 priced responses (one in the alias-invalid attempt), one unpriced response, and eight denied calls in the startup-invalid cohort. Final-answer copies are not additional calls. The prior 24 reissues and the separate 50-case prediction diagnostic are different populations and are not pooled here.

Signed unit-price error is `(proposed unit / hidden historical target unit − 1) × 100%`; negative means under target, positive means over target. Absolute percentage error (APE) discards direction. The APE-change column is **final APE minus first-call APE** in percentage points (pp), so negative means improvement. These percentages do not reveal dollar-price differences: an equal percentage miss can represent different dollar errors at different target prices, and an extended-dollar miss also depends on quantity. No private prices or quantities are reported.

| Generated case | First automatic signed error | Final signed error | APE change | Status |
| --- | ---: | ---: | ---: | --- |
| `development-b01-q1` | −84.669282% | −76.762715% | −7.906568 pp | Valid pair; improved, still outside tolerance |
| `development-b01-q2` | +93.540401% | +301.328558% | +207.788157 pp | Valid pair; worsened |
| `development-b01-q3` | −77.432745% | — | — | Priced response explicitly held/unadopted; alias-invalid, excluded from valid aggregates |
| `development-b02-q1` | −31.185254% | −32.820476% | +1.635221 pp | Valid pair; worsened |
| `development-b02-q2` | −92.600995% | −95.362359% | +2.761365 pp | Valid pair; worsened |
| `development-b02-q3` | Unpriced | +258.718252% | — | Valid final draft, but no paired numeric delta; missing is not zero |

The old `initial_automatic_APE` values numerically match the **baseline** first calls, not V2 first calls. The archived fields do not themselves bind call provenance, so this is a reconstruction and numerical correspondence, not an undocumented certainty about their origin.

| Measure | First automatic, same four valid complete pairs | Final, same four valid complete pairs | Five valid final drafts (different denominator) |
| --- | ---: | ---: | ---: |
| Mean absolute percentage error (MAPE) | 75.498983% | 126.568527% | 152.998472% |
| Mean signed error (bias) | −28.728783% | +24.095752% | — |
| Population variance of signed errors | 5,541.196649 pp² | 26,135.039118 pp² | — |
| Population standard deviation of signed errors | 74.439214 pp | 161.663351 pp | — |
| Median APE | — | — | 95.362359% |
| Inside ±20% | — | — | 0/5 |

On the four like-for-like cases, MAPE **increased 51.069544 pp** and signed-error variance increased roughly **4.72×**; bias moved from underpricing to overpricing, driven especially by `development-b01-q2`. The five-draft MAPE is a coverage-inclusive final snapshot, **not** an improvement comparison against the four-case first-call mean. The held and unpriced responses and the eight denied calls cannot be treated as zero errors or as successful prices. All five valid final drafts failed V3 only because their unit prices were outside tolerance; none failed extension arithmetic.

A single global markup or inflation multiplier cannot put all five final drafts inside the ±20% band. For a multiplier `m`, each case requires `0.8 × target/proposal ≤ m ≤ 1.2 × target/proposal`. The intersection is empty: `development-b02-q2` requires at least 17.2502×, while `development-b01-q2` allows at most 0.2990×. These are retrospective diagnostic bounds, not proposed customer prices or deployable calibration factors.

## Replayed mechanisms and limits

Each of the 12 original first-automatic outputs was reproduced exactly with its hash-verified persisted corpus and original inputs. That replay validates the recorded first-call behavior, but does not establish that a different input or source would produce an accurate final price.

- In `development-b02-q3`, request-note boilerplate and disclaimer grew the total request retrieval-token count from seven to 30; the seven includes description tokens. The recorded input admitted no candidates. Replacing **only** the notes with the verbatim frozen specification admitted three candidates, yet still missed the target by +126.65%. That repairs input sensitivity and coverage, not accuracy. Verbatim notes did not change the price in the other four valid matched cases.
- In `development-b01-q2`, normalization stripped question marks from a partially masked part identifier, yielding a prefix-plus-same-customer score of 0.90. Automatic fallback accepts scores ≥0.30 and takes a weighted median of interpolated prices from different parts; the agent's final draft instead copied another component's same-quantity curve without justified scale adjustment and magnified the error. Removing all notes as an intentionally unsafe ablation moved this case to −18.69%, but discarded supplied process/finish requirements and worsened `development-b02-q1` to −88.01%. It is not a shippable fix.
- In `development-b02-q1`, a different interpolation formula on one curve worsened APE only 1.64 pp. Unit selection and analogy dominate the miss, not cent arithmetic. Copying a price at an exact quantity from a distinct component does not establish engineering equivalence.

No pricing algorithm or acceptance threshold changed, and these diagnostics do **not** justify an accuracy improvement or 90% success claim. New per-turn grader diagnostics make the direction and magnitude of future misses visible. Source access and protocol remediation remain separate follow-ups, not reasons to skip numerical analysis.

## Verification

The extended grader was run against all 18 retained attempts into new private report files. Every original grade field remained equal, including all V/J criteria, reasons, scores and all-pass results; it added 27 turn records and 18 finite priced-response observations without altering the original artifacts. Local verification passed 86 TypeScript tests, 108 Python tests, 39 script tests, 11 synthetic order scenarios, TypeScript build/evaluation checks and the native plugin typecheck. These checks validate the diagnostics, not pricing accuracy.
