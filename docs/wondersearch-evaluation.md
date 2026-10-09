---
type: source::au-base-types
tldr: "Steve WonderSearch lane: tested offline scaffold, blocked live comparison, unchanged frozen cohort and no measured retrieval gains."
origin: https://docs.evokoa.com/wondersearch/sdk/installation
---

# Steve — WonderSearch implementation and evaluation report

**2026-10-09 · Partial implementation; live evaluation blocked.** No original
documents were uploaded, no isolated drive was created, and no paid searches
were made. This report does not establish a WonderSearch quality, latency, cost
or pricing improvement.

## Delivered

- A default-off, evaluation-only retrieval adapter with synthetic scope,
  budget, immutable receipt and citation-validation tests. Production retrieval
  and pricing are unchanged.
- `wondersearch==0.2.0` search/upload request mappings tested against the actual
  SDK with in-memory transport. The live constructor deliberately stays closed,
  even when enabled; this is **not a working live importer**.
- A reproducible offline CLI that checks frozen input and baseline hashes and
  retains every case in blocked reports. Source, claim and map records use native
  Ars Umbris types.
- 32 passing synthetic tests, including the optional pinned-SDK tests. The
  canonical verifier passes; its two optional SDK skips are covered separately.

## Comparison results

The same 250-case development cohort and historical acceptance criteria are
retained. A planned query is not an attempted or completed case.

| Metric | Baseline paired arm | Small | Medium | Large |
|---|---:|---:|---:|---:|
| Frozen cases | 250 | 250 | 250 | 250 |
| Newly attempted comparisons | 0 | 0 | 0 | 0 |
| Not run | 250 | 250 | 250 | 250 |
| Independently labelled retrieval quality | Not measured | Not measured | Not measured | Not measured |
| Citation correctness | Not measured | Not measured | Not measured | Not measured |
| Manufacturing-compatible evidence | Unknown | Unknown | Unknown | Unknown |
| Latency / actual billed cost / served effort | Not measured | Not measured | Not measured | Not measured |
| Improved / regressed cases | Not measured | Not measured | Not measured | Not measured |
| Paired pricing outcomes | Not measured | Not measured | Not measured | Not measured |

**Separate historical pricing diagnostic:** the previously retained baseline
report was checked against the pinned code, registers, complete cohort and
configuration, not rerun: 220 priced, 30 no-analog, 0 unreplayable, and 45/250
passing all five unchanged criteria. This is neither a WonderSearch comparison
nor a true historical backtest, current-cost accuracy, realized margin or >90%
end-to-end success. The ±20% criterion remains a historical diagnostic.

## Why live execution stopped

1. **Original-document scope is not established.** Existing price-row scopes
   cannot silently authorize full original text. Partial archived case matches
   and metadata candidate sets do not bind whole-document permissions. The
   documented search boundary is one drive and an optional nonrecursive folder,
   not an arbitrary per-case document/hash/date filter. Post-filtering results
   would not prevent retrieval leakage.
2. **The measured full source sets exceed the cap.** The 39,975 originals total
   2,634,657,836 bytes; the 7,845 price-referenced originals total 1,268,957,730
   bytes, above the conservative 1,000,000,000-byte limit. This does not prove
   every narrower design impossible, but no narrower frozen, authorized design
   preserving the requested scopes has been established. No cases were sampled
   away and no originals were replaced with surrogate text.
3. **Billing and storage cannot yet be bounded authoritatively.** The workspace
   key succeeded on three read-only context/capability/drive-list probes. Wallet
   and storage access require a signed-in user token. Available credits, used and
   reserved storage, and import/processing/storage charges remain unverified.
   Small/Medium/Large are advertised as available, but were not exercised live.

The nominal 250-search forecasts are $0.25 / $0.625 / $2.50, or **$3.375 total
before other charges**. This is not actual spending or proof the full run fits
within $5. No top-ups, upgrades, production activation, policy resolution or
merges occurred. The prior live ledger remains unchanged. Recorded paid calls
are zero; account-level billed cost is unverified, not silently asserted as zero.

## Reproduce and inspect

See [[map - WonderSearch isolated evaluation boundary]] for exact CLI commands,
private-input restoration, test commands, remaining live-runner work and the
earlier verifier failures/retries. Public synthetic tests require no private
corpus or credential:

```sh
python3 -B -m unittest discover -s scripts/test -p 'test_wondersearch*.py' -v
node scripts/verify.mjs
```

Install the pinned optional SDK from `scripts/wondersearch-requirements.txt` in
an isolated Python environment to exercise both SDK contract tests; otherwise
they explicitly skip. No live request is made by these commands.

Machine-readable aggregates, exact input/code/report digests and retained
baseline accounting: `evals/wondersearch-offline-review.public.json`.

**Provenance correction:** final portability-only test edits changed the source
fingerprint after the initial review-v4 report was sealed. Review-v5 reissues
the blocked artifacts against the final code and a new public-source binding
regression test. Older artifacts remain preserved, not overwritten or relabelled.
No scored outcome, case, scope, criterion or baseline execution changed.

The optional boundary/CLI currently requires POSIX file ownership/locking
semantics. Its test modules explicitly skip on non-POSIX systems; no Windows
boundary coverage or live adapter is claimed.

- Frozen plan: `7199501d8dfc75ac7072a458a474f8923cbb36c398f44b6c99af6059ffec10a3`
- Baseline commit: `34a0880037cf1cd40ae062e68b7201ad0b8c4cd9`
- Case file: `12414d36a0f2d721d86d74dea61a66673c043931668f7573ece4f27553445311`
- PDF register: `a7d84545b00ecb3f976d100d3e214885cca009189c1f59c500687539e5728757`

Per-case artifacts, original documents, target prices, credentials and provider
identifiers remain private and are not included in this report or the PR.

**Next required evidence:** a whole-document, pre-retrieval scope binding that
preserves the frozen cohort/exclusions within 1 GB, and authoritative remaining
credits/storage/charge terms. The live transport/importer also needs reviewed
one-attempt execution and durable upload recovery; a flag alone cannot activate
this scaffold. Do not change scopes, budget or pricing policy to force a result.
