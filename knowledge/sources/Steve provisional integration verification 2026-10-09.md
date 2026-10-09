---
type: source::au-base-types
tldr: "Approved review-only provisional fallback preserves screening verdicts and human approval; matched post-integration PDF replay stays 46/250 passes and fails the median-error regression check."
origin: "Synthetic regression tests and offline 250-case frozen-snapshot replay comparing main 727fda8b with integrated estimator e8904313"
---

## Policy integration and reproduced handoff defect

The approved integration keeps a clearly labeled provisional proposal when enabled Jev admits no analog. It selects only a screened usable candidate, excludes explicit engineering conflicts and unavailable screening, and cannot bypass zero screening budgets or use an unscreened tail. Rejection/quarantine remains distinct from admission, adoption and human approval. Offline holds remain holds; no paid service, mailbox, scheduler or customer release was enabled.

Integration tests found that `JevClient.chooseStrategy` previously constructed every strategy packet with `ADMITTED`, including the provisional fallback. Three synthetic regressions reproduced rejected/quarantined verdict loss and invented admission on a direct strategy call without a verdict. The estimator now passes screening verdicts by composite candidate key; strategy packets preserve them and default missing verdicts to `NOT_SCREENED`. Strategy instructions, the estimator skill and the order contract agree with this policy. No real provider was called in these tests.

Latest main's original-request binding checks are retained before the scoped-order projection. Named human review and `customer_release_authorized: false` remain intact. Unrelated local should-cost/provider work was excluded from integration commits and checked byte-for-byte against its private pre-integration manifest.

## Matched historical replay, not end-to-end accuracy

Both arms use the same previously exposed 250-case customer-PDF cohort, original registers, exclusive recorded-date cutoff, source-quote exclusions and unchanged 20% historical price tolerance. All holds and invalid attempts remain in the denominator. Target fields are not passed into `estimate`; no target-derived tuning was performed. This is a development/code-regression diagnostic, not untouched confirmation, a model-driven Jev evaluation, current-cost accuracy or realized-margin validation.

| Register / metric | Latest main | Integrated |
| --- | ---: | ---: |
| PDF cases / priced / held / invalid | 250 / 218 / 32 / 0 | 250 / 218 / 32 / 0 |
| PDF all-pass / all cases | 46/250 (18.4%) | 46/250 (18.4%) |
| PDF median APE, priced only | 55.4395% | 55.6905% |
| PDF mean APE, priced only | 118.4795% | 112.4345% |
| Internal cases / priced / held / invalid | 250 / 242 / 8 / 0 | 250 / 242 / 8 / 0 |
| Internal all-pass / all cases | 51/250 (20.4%) | 53/250 (21.2%) |
| Internal median APE, priced only | 53.5062% | 55.6311% |
| Internal mean APE, priced only | 101.8235% | 106.4974% |

PDF transitions: 3 fail-to-pass and 3 pass-to-fail. Internal transitions: 5 fail-to-pass and 3 pass-to-fail. Both unchanged `compare.ts --fail-on-regression` checks exit 1 because median APE worsens; neither is a clean pricing-performance improvement. The earlier pre-integration 45/250 PDF result belongs to its original commits and is not relabeled. The approved enabled-Jev fallback is covered by synthetic tests, not these offline replays. The >90% end-to-end goal remains unproved; a separate untouched confirmation is still required.

## Reproducibility and verification

Private artifacts use the `post-integration-v2` prefix; the retained baseline uses `post-integration-main`. The private plan binds both source manifests before execution, original input hashes and retained baseline-report hashes. Earlier post-integration artifacts are preserved. Re-running each final candidate produced identical per-case results to the initial integrated run; the later strategy-handoff correction changed the source fingerprint but not the offline results.

| Binding | SHA-256 |
| --- | --- |
| Cases | `12414d36a0f2d721d86d74dea61a66673c043931668f7573ece4f27553445311` |
| Selected IDs | `2acbbe76ec4b08e33ccfaf9e48b040c42d4448c0f2c2f72e870d571f1351b38a` |
| PDF register | `a7d84545b00ecb3f976d100d3e214885cca009189c1f59c500687539e5728757` |
| Internal register | `6ed19d0cf550f3e65f420b676bbc4354c8dfaf05912d1f5f4edefb4bc8b24cfe` |
| Main source + lock | `049965ae83ae335a05e213ab6b009947b1de8516701535e381335d0bfcfcef3e` |
| Integrated source + lock | `24089f371fd6dc6121a3e08c04e8bc7a38a09c596a006b0b65f80b9665a613f7` |
| Main PDF report | `8bc0a9a2e59c9ab9278cf189315abb784b8de0e97c83aca817937fdbed681a9e` |
| Integrated PDF report | `7b6c40ea9b30baf5262731193a3a595f1dd1900ef83442d819b21c8ffadf37f8` |
| Main internal report | `238e7837c983041afcde867e447c4a907c319a5b599557dd93a31bb087420e7c` |
| Integrated internal report | `edd5f431f4eaa4b30d3ea55e6cb9549615089776dd609d5daaf5615e989b47d4` |

Follow the canonical eval skill: run `evals/run-eval.ts` from each pinned checkout with the exact private case file and explicit matching register, no sampling or retrospective/Jev flags, and new owner-only report filenames outside Git. Compare matching JSON reports using `evals/compare.ts --report <new-private-comparison.md> --fail-on-regression`. Execution timestamps make whole-report hashes run-specific; compare provenance/configuration and per-case results when replaying. Never commit private case rows, targets or report bodies.

Canonical local verification passes: 208 estimator tests, build and both TypeScript checks, 204 Python tests, 56 script tests and 11 synthetic order tasks. No lint command is configured; `git diff --check` passes. Verification used a credential-free environment and process-local Git-config isolation for synthetic runtime fixtures. These software checks do not override the failed historical regression checks or establish current cost/margin correctness.
