---
type: source::au-base-types
tldr: "The 208 development-tagged replay cases lack structured engineering/cost inputs and same-part history outside their excluded source in the frozen customer-PDF register; this is not evidence that the full Keller archive lacks those facts."
origin: https://github.com/OpulentiaAI/keller-quotes/pull/29
---

## Population and unchanged score

This is an operator-only diagnosis of the **retained** customer-PDF historical
replay at baseline `34a0880037cf1cd40ae062e68b7201ad0b8c4cd9`, not a new pricing
run, WonderSearch result, independent relevance judgment or current-cost test.
The whole-cohort result remains **45/250 historical passes** with the unchanged
five criteria and 20% unit-price tolerance. All 250 remain in that denominator.

Only the existing **208 development-tagged cases** were drilled into. The other
42 were not used for case-level diagnosis, selection or tuning. The existing
hash-based split does not restore untouched confirmation: the whole cohort's
results were already exposed in prior diagnostic work. No labels or oracle
fields were passed to retrieval; only the frozen request fields, source exclusion
and cutoff were supplied. No model, pricing or provider call was made.

## Measured observations

| Development observation | Count / denominator |
|---|---:|
| Historical all-criteria pass | 33 / 208 |
| Priced but outside the unchanged 20% tolerance | 151 / 208 |
| Held without price | 24 / 208 |
| Same normalized part outside the excluded source in the frozen PDF register | 0 / 208 |
| Priced cases exposing only other-part analogs | 184 / 184 priced |
| Nonempty customer ID, part number and quantity fields | 208 / 208 each |
| Nonempty description field | 200 / 208 |
| Explicit material, finish, drawing reference, revision, thickness, dimensions, tolerances, routing or costing inputs | 0 / 208 each |

The 24 holds separate into **11 with no retrieval candidate** and **13 with
candidates but all top-three scores below the frozen deterministic admission
threshold of 0.3**. Jev was disabled in this baseline; these are not live Jev
rejections. All 184 priced development cases have at least one candidate passing
that unchanged rule. This does not establish manufacturing compatibility.

Twelve development requests lie outside every usable top-12 candidate's recorded
quantity range. That is a diagnostic review flag, not a new failure criterion,
a measured pricing cause or proof of incompatibility.

## Interpretation and next admissible work

This test currently supplies mostly identifiers, description and quantity to a
historical-price engine. More retrieval hits cannot by themselves prove a
material/routing/cost-plus quote. Lowering the admission threshold would change
pricing policy and does not establish better accuracy; it was not attempted.

**Missing structured fields are not proof of missing source facts.** Descriptions
may contain engineering details, and the private archive contains more than the
frozen customer-PDF price register. This audit did not parse drawings or establish
that the wider internal register lacks same-part evidence. The measured result
locates a handoff and test-input limitation, not a justification to buy more data
or broaden frozen scopes silently.

Next: on separately authorized development inputs, bind RFQ/drawing engineering
facts to their original source locations, distinguish known/conflicting/unknown
requirements, and join applicable material procurement and routing/rate evidence
into the reviewed costing worksheet. Freeze that new workflow evaluation and an
actually untouched confirmation set before scoring it. Preserve this 250-case
historical diagnostic unchanged. [[map - WonderSearch isolated evaluation boundary]]
continues to govern the blocked retrieval comparison and resource limits.

## Reproduction and evidence

The public operator script is `evals/diagnose-development-evidence.mjs`; aggregate
output is `evals/steve-development-evidence-diagnostic.public.json`. Private
case-level outputs remain outside Git. The script pins the baseline commit,
tracked cleanliness, case/register/report bytes, baseline source/lock digest and
ordered case identities. It reuses that baseline's actual `QuoteRegister` and
`retrieve` functions; it does not substitute a new retriever or pricing policy.

With the existing private inputs, a private owner-only output directory outside
Git, and the frozen baseline's installed `tsx`:

```sh
env -i PATH="$PATH" HOME="$HOME" LANG=C.UTF-8 \
  "$BASELINE/estimator/node_modules/.bin/tsx" \
  evals/diagnose-development-evidence.mjs \
  "$BASELINE" "$CASES" "$REGISTER" "$RETAINED_REPORT" "$PRIVATE_OUTPUT"
```

`PRIVATE_OUTPUT` must be a fresh absolute filename; existing artifacts are never
overwritten. Only aggregates are printed. Wrong case/report hashes and a
nonprivate output directory are rejected without echoing private arguments.
Verification exercised those rejections, immutable-output preservation and a
byte-identical replay. The public report carries the input, script and private
artifact digests. Prior diagnostic iterations remain private and preserved.
