---
type: source::au-base-types
tldr: Source-selection, binary-tag and privacy contract for the separately shipped historical full-data builder.
origin: https://github.com/opulentiaai/keller-quotes/commit/cf1ee175f9789ed707190ee13ca7e734f7c32a1a
---

The [full-data contract](https://github.com/opulentiaai/keller-quotes/blob/cf1ee175f9789ed707190ee13ca7e734f7c32a1a/docs/full-data-case-set.md) and [source-assessment contract](https://github.com/opulentiaai/keller-quotes/blob/cf1ee175f9789ed707190ee13ca7e734f7c32a1a/docs/ground-truth-assessment.md) belong to a separately shipped analysis branch, not this documentation's main-branch implementation.
This source preserves what that builder checks without merging its estimator, workflow or dataset-tooling changes.

Historical full data requires a complete original RFQ and sent customer quote, independently accepted customer order, directly linked closed manufacturing job, complete actual material/labor/outside/setup ledger, compatible manufacturing identity, exact quantity/currency/UOM, consistent chronology and independent source review.
Membership is a fixed AND of ten mandatory conditions, never a configurable subset or a model-score filter.
Binary one means the supplied source condition has been verified, and binary zero means not established rather than a verified business negative.
Current-2026 vendor freshness and business optimum are separate optional classifications, not prerequisites for observing an old closed job.

The builder reexecutes the original pinned assessment and ignores its owner-created confirmed-evidence assertions.
It reopens whole-file and physical-record receipts, validates candidate customer/part identity, deduplicates records and chains, retains rejected alternatives, and rechecks source pins before publication.
The 128 MiB allowance is confined to the SOMAST/SOLOTS/WOHEAD/WOJOBS native-chain roles; all ordinary helper and WOHEAD candidate reads retain the 64 MiB bound.
Native pointer equality has the explicit state `QUOTE_LEVEL_ERP_POINTER_ONLY` and never substitutes for a mandatory acceptance, manufacturing, quantity or cost condition.

Original case bytes and target values remain unchanged in eligible/excluded outputs.
Every case remains in the binary-tag audit with state, reason, provenance and exclusion accounting, even when the eligible JSONL is empty.
All outputs, hidden targets, tags, later acceptance and actual-cost records are operator-only; the builder generates no blinded worker context and changes no worker-file allowance.
Selection uses source availability and confirmation, never predicted prices, model scores or post-run success.

Structured primary records, independently reviewed source authenticity and trustworthy closure/ledger enumeration are external obligations, not facts produced by an issuer string or a local receipt.
The software's mechanical checks do not cryptographically authenticate a person, prove independent execution, certify business optimum or authorize customer release.

| Sealed implementation | SHA-256 |
|---|---|
| `keller-full-data-set.py` | `2c333596f9a3e8c0340a7c367f5ca58f44515e88315e9d8b51e5b0b92bc77759` |
| `keller-ground-truth.py` | `176955d70c460a1fcca0c371cd4a48df5b832373bf6f84f393d33201dc5a91f6` |
