---
type: source::au-base-types
tldr: "Synthetic faults showed native quote drafts could reach review without binding to the caller's request; request-file, provenance-hash and embedded-request checks now reject that drift."
origin: "Repository-local native quote-tool integration tests against main 380c2172bbe8c584e8375a48c6149534235bb27d"
---

## Observed defect

`arsumbris/quote/tool.ts` verified the selected register hash but did not compare
the generated request hash with the caller's original request. In synthetic
native-tool tests, each of these faults still returned a review package:

- The export subprocess changed a cost-plus line's quantity from 3 to 999 after
  request validation, before pricing. The resulting artifact consistently
  described the changed request, rather than the request the caller supplied.
- The returned artifact carried an incorrect request provenance hash.
- Its embedded request changed while its provenance hash remained unchanged.

These were controlled fault injections with a fake exporter and synthetic CSV,
not observations of production incidents or unauthorized customer delivery.
The initial test run reported three regression failures; the existing native
quote tests passed. No private corpus, targets or provider calls were used.

## Correction and reproduction

The tool captures canonical request JSON and its SHA-256 before any subprocess.
It checks that the request file is unchanged before and after pricing, and that
both the generated provenance hash and embedded request bind to that captured
request. A mismatch returns the existing redacted error and removes the draft
instead of producing a review receipt. Named human review and the prohibition
on customer release remain unchanged.

The regression suite additionally simulates request-file drift after pricing,
checks failed-draft cleanup, and verifies formatted/Unicode JSON still works.
Successful explicit, cost-plus, historical and blocked drafts must agree on the
request identity across their stored request, order, response and review receipt.

```sh
env -i PATH="$PATH" HOME="$HOME" LANG=C.UTF-8 \
  python3 -B -m unittest discover -s tests -p test_arsumbris_quote.py -v
```

## Interpretation boundary

This is a handoff-integrity fix, not evidence that supplied material prices,
labor costs, routing or margins are correct. It does not independently recompute
the quote, authenticate sources, calibrate confidence or establish current-cost
accuracy. It changes no pricing formula or admission policy, frozen cohort,
cutoff, denominator, tolerance, production configuration or WonderSearch gate.
No pricing evaluation or historical-accuracy gain is claimed. The pending
pricing-policy merge is untouched.
