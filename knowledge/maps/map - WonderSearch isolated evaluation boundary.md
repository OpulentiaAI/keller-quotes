---
type: map.overview::au-weave
tldr: "Operator entry point for the additive offline WonderSearch boundary, reproducible blocked reports and remaining live-execution gates."
about:
  - "[[c-keller-mfg]]"
---

Read [[WonderSearch official SDK and isolation contracts]] for official evidence and [[WonderSearch retrieval must remain blocked until whole-document scope and resource bounds are proved]] for the admission boundary.

The concise [implementation and evaluation report](../../docs/wondersearch-evaluation.md) presents the all-case comparison table, blockers and separate pricing diagnostic.

## Delivered boundary, not live activation

- `scripts/wondersearch_boundary.py`: default-off **evaluation-only** adapter seam, narrow structured RFQ, exact whole-document scope validation, revision/text/UTF-8 citation checks, private immutable writes, synthetic durable budget ledger and independently labelled paired-summary primitive. It is not imported by production retrieval or pricing.
- `scripts/wondersearch_sdk_contract.py`: pinned 0.2.0 request mappings for search and original-file upload; synthetic SDK construction accepts only in-memory `httpx.MockTransport`. `live_client(enabled=True)` unconditionally refuses. Mapping functions alone do not supply authorization, retry protection or a live importer.
- `scripts/wondersearch-eval.py`: offline `import-plan` / `eval-blocked` commands. Both validate the same frozen inputs and produce the same immutable blocked artifacts; neither contacts a provider nor executes the baseline estimator. This is intentionally a **partial offline implementation**, not a runnable paid evaluation.
- `scripts/wondersearch-requirements.txt`: exact optional SDK pin. No SDK is needed for the offline CLI or core tests. No dependency on unpinned WonderSearch is permitted.
- `scripts/test/test_wondersearch_boundary.py` and `scripts/test/test_wondersearch_sdk_contract.py`: synthetic fixtures only. SDK tests use a fake key and no sockets, never the operator credential.

## Reproduce locally

The optional offline boundary/CLI currently requires POSIX ownership, `flock` and no-follow file semantics. Its test modules explicitly skip on non-POSIX systems rather than breaking the existing cross-platform verifier; this is not Windows boundary coverage or a Windows live adapter.

Run in the assigned implementation worktree. Set `RUN_DIR` to the assigned owner-private run directory, and `PLAN`, `CASES`, `REGISTER` to the original frozen files; never put copies in the checkout. Set `BASELINE_REPO` to the read-only, clean baseline worktree at `34a0880037cf1cd40ae062e68b7201ad0b8c4cd9`. The CLI enforces that commit and input digests rather than treating the implementation checkout as baseline. `RUN_DIR` may be any canonical owner-private directory outside Git checkouts; this session must use its assigned run directory. Use `--preflight-dir` to read the retained preflight from a separate location (defaults to `RUN_DIR`). A restored preflight bundle retains the original pinned bytes under their direct-child filenames; historical absolute paths in its manifest do not force the original workstation layout, and duplicate restored filenames are rejected.

```sh
WONDERSEARCH_SYNTHETIC_TEST_DIR="$RUN_DIR" python3 -B -m unittest discover -s scripts/test -p 'test_wondersearch*.py' -v
python3 -B scripts/wondersearch-eval.py import-plan \
  --run-dir "$RUN_DIR" --plan "$PLAN" --cases "$CASES" \
  --register "$REGISTER" --baseline-repo "$BASELINE_REPO"
python3 -B scripts/wondersearch-eval.py eval-blocked \
  --run-dir "$RUN_DIR" --plan "$PLAN" --cases "$CASES" \
  --register "$REGISTER" --baseline-repo "$BASELINE_REPO"
```

Synthetic tests need no private archive: without `WONDERSEARCH_SYNTHETIC_TEST_DIR` they create and remove their own mode-0700 temporary directory. They are also included in `node scripts/verify.mjs`. For actual pinned SDK contract coverage, replace `python3` in the test command with an existing private environment's Python containing `wondersearch==0.2.0`. Without that SDK, two explicitly optional tests skip. The CLI prints only an allowlisted aggregate/hash summary or a fixed error code. It never prints arbitrary argument values, SDK exceptions or per-case results. Private files are mode 0600 under a mode 0700 directory. Identical resumes preserve bytes; changed or partial files fail closed instead of being overwritten.

Produced artifacts are `review-v5-source-manifest.blocked.private.json`, `review-v5-query-sequence.blocked.private.json`, `review-v5-paired-report.blocked.private.json` and `review-v5-summary.public.json` under `RUN_DIR`. `--artifact-prefix` can select a fresh immutable filename prefix after a reviewed code change; it cannot overwrite previous evidence. Earlier implementation artifacts, including v3 and review-v4, remain preserved but are superseded by review-v5. Public summary means content is publication-safe; it is still written privately. Every one of the 250 cases appears in each of the baseline/Small/Medium/Large arms as `not_run`, with explicit per-arm reasons; measured cost, latency, relevance, gains/regressions and pricing outcomes remain null. Original preflight inventory and ledger digests are bound, not reinterpreted as upload authorization. A separately retained baseline diagnostic is not a newly executed arm of this blocked comparison.

Review-v5 corrects a parent-stage provenance defect: the final non-POSIX test guards changed the implementation fingerprint after review-v4 was sealed. Fresh blocked artifacts now bind the final code and an added regression test that checks the published implementation hash using only public files. The stale report was not relabelled; old receipts and its digest remain retained. Any later edit to the fingerprinted implementation/test files requires new blocked artifacts before updating the public report. No source scope, criterion, denominator or scored result changed.

## Independent offline safety review

The aggregate-only machine-readable report is `evals/wondersearch-offline-review.public.json`. The review made **zero provider requests, paid searches, uploads or drive creations**. The inherited ledger records three GET-only probes; saved HTTP 200 responses are not proof of available credits, used/reserved storage or reconciled billing. Ledger bytes remain unchanged. Inventory assertions were validated against retained preflight receipts, not a fresh rehash of every original. The 7,845 price-referenced originals total 1,268,957,730 bytes, above the conservative cap; metadata candidate sets remain unauthorized. No live search is safe.

Focused corrections now require a saved, operation-bound receipt for budget settlement; preserve known charges when citation verification rejects a response without retaining rejected passages; retain full reservations on missing/invalid accounting or failed receipt persistence; and use local high-precision decimal arithmetic. Scope declarations reject missing exclusions, malformed document/target identifiers and duplicate membership. A failed preflight validation cannot be promoted. The injected callable remains trusted synthetic test code, not a sandbox or proof of server membership.

Verification: **32 synthetic tests passed with the actual pinned SDK and mock transport**. The credential-free canonical `node scripts/verify.mjs` passed, including 110 estimator tests and the script/benchmark stages; its system-Python WonderSearch suite intentionally skips two optional installed-SDK tests, covered by the separate pinned-SDK run. The source-binding regression first failed against the stale report, then passed after immutable artifact reissue. `git diff --check` passed. An earlier verifier run with an overridden private `TMPDIR` failed; the retry without that override passed. The original failure's precise cause was not retained, so this is not claimed as a diagnosed fix.

### Separately validated retained baseline, not retrieval gains

A pre-existing 250-case baseline report was independently matched to the frozen case/register hashes, complete ordered case IDs, `34a0880037cf1cd40ae062e68b7201ad0b8c4cd9` source+lock digest and cutoff-aware/Jev-disabled configuration. All cases and target quantities/prices were checked privately; exposed analogs exclude each source quote. No baseline was newly executed during this review. The verified copy and aggregate projection are retained privately as `review-v4-offline-baseline.verified.private.json` and `review-v4-offline-baseline.summary.public.json`.

| Retained historical diagnostic | Count / all 250 cases |
|---|---:|
| Priced | 220 |
| No analog | 30 |
| Unreplayable | 0 |
| All five unchanged deterministic criteria passed | 45 |
| Unit price within unchanged historical ±20% tolerance | 45 |
| Exposed source-exclusion / recorded-cutoff checks passed | 250 / 250 |

These are development-cohort historical diagnostics, **not** WonderSearch gains, a blind holdout, a true historical backtest, independent retrieval relevance, current manufacturing applicability, market-current cost or realized margin. Missing revision metadata is not verified. No full-document authorization follows from this baseline. The paired report deliberately remains all-arm `not_run`; its null comparison metrics must not be replaced with these separate diagnostics.

## Remaining gates for a separately reviewed live implementation

1. Bind whole-original-document authorization to every frozen case without enlarging price-only scopes. Partial archived matches and metadata candidate sets are not permissions.
2. Freeze a narrower original-only manifest and immutable server scope that satisfy the 1,000,000,000-byte conservative experiment limit. Do not upload the full archive or target/register/oracle files; do not substitute redacted or surrogate text for originals.
3. Verify available credits, used/reserved storage and all import/processing/storage charges authoritatively. Forecast the complete run within $5; prohibit purchases/top-ups/upgrades and account for concurrent external consumption.
4. Review a single-ledger migration/reconciliation preserving all prior receipts; freeze reviewed query bytes, hashes, case order, scope and effort before any judgments. All efforts must see the same permitted evidence and sanitized RFQ.
5. Implement and independently test SDK-level one-attempt guards, per-stage upload receipts, partial-failure recovery, private subprocess output containment and child-only credential binding. The environment builder strips the source credential variable and all unrelated credentials/telemetry; it does not launch a process or modify existing Polygres configuration.
6. Keep the pinned baseline and unchanged arithmetic/admission policy separate from retrieval. Do not run the implementation checkout as the frozen baseline. No Jev/provider calls, sends, approvals, merges or production defaults are enabled by this lane.

A future real paid runner must be new reviewed work; setting a flag in this partial scaffold is not sufficient.
