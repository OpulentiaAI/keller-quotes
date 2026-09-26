# Execution and release verification

Keller is an offline quote-draft workflow with optional external integrations. Passing repository checks does not prove live Polygres behavior, a durable host binding, or customer-ready pricing. Keep those acceptance gates separate.

## Shipped-work trace

Repository history reviewed on 2026-09-26, through `4cc5b23`. All six prior pull requests are merged; there were no open PRs or issues at the start of this audit.

| Work | Delivered | Boundary still to verify |
|---|---|---|
| Initial extract (`8f4883e`) | Frozen CSV/JSON register: 179,608 rows and 40,111 quotes | A fresh source extract needs owner authorization; do not edit the register by hand. |
| [#1](https://github.com/OpulentiaAI/keller-quotes/pull/1) | Historical analog estimator, agent workflows, fixed 250-case eval set | Accuracy is not sufficient for unattended pricing; the original report exposes future data. |
| [#2](https://github.com/OpulentiaAI/keller-quotes/pull/2) | Normalized Polygres schema, embedding/graph/FTS layers, loaders | Original live verification predates the later refresh changes; disposable stubs cannot verify installed extension/grant/index behavior. |
| [#3](https://github.com/OpulentiaAI/keller-quotes/pull/3) | Dataset-specific analysis workflow and grain rules | Analysis must distinguish quote grain from price-break grain and never invent lost outcomes. |
| [#4](https://github.com/OpulentiaAI/keller-quotes/pull/4) | C. Keller brand overlay for `au-host @ 0e85fb1` | This is a drop-in overlay, not a standalone host deployment or scheduler. Verify it in the approved host checkout. |
| [#5](https://github.com/OpulentiaAI/keller-quotes/pull/5) | Input validation, Jev ordering, safe CSV output, CLI path fixes, CI | Hosted checks could not start because of GitHub account payment/spending restrictions. |
| [#6](https://github.com/OpulentiaAI/keller-quotes/pull/6) | Transactional refresh, cutoff-aware replay, recoverable offline draft queue, host-binding proposal/validator | Request producer, human reviewer, authenticated host observations, and fresh-run persistent-workspace proof are deployment gates, not consequences of merging. |

The 2026-09-24 coordination record reported local passes and explicitly left live host onboarding unproven. On 2026-09-26, the latest main-branch workflow [36023157830](https://github.com/OpulentiaAI/keller-quotes/actions/runs/36023157830) still recorded both jobs as **not started** because of account payment/spending restrictions. This is infrastructure failure, not a failing test and not a green CI result. This project had no registered Capy automations when audited; that does not rule out a scheduler on another host.

## One verification path for developers and CI

Use Node 24 or newer. From the repository root:

```sh
cd estimator
npm ci
cd ..
node scripts/verify.mjs
```

The verifier runs estimator/eval tests, the TypeScript build, a compiled CLI smoke that validates fully priced offline output, and local worker/export/capability tests. It resolves paths from its own location and expands script test paths without a shell glob. It stops on failure, does not install dependencies, and strips gateway and production database credentials from child processes. This proves local behavior, not integration readiness. CI calls this same entry point rather than maintaining a separate checklist.

Database tests are a separate explicit mode. Start a **disposable local** PostgreSQL 16 server whose test role can create databases, install Python dependencies, then run:

```sh
python -m pip install -r requirements-db.txt
# Set KELLER_TEST_DATABASE_URL to your disposable local PostgreSQL URL.
node scripts/verify.mjs --database
```

The mode fails if the test URL is absent or nonlocal, instead of accepting a skipped database suite. The tests create/drop isolated databases and stub pgContext; never substitute a production URL. Both verifier modes must pass for changes spanning the estimator and database paths. Dependency changes also require `npm audit` from `estimator/` and an unchanged offline replay unless pricing changes are intentional. There is no separate configured lint command; the TypeScript build is the repository's type check.

CI also runs when the canonical scheduled-job prompt changes, because the automation exporter consumes that Markdown as executable input. Manual dispatch permits a rerun after restoring runner access; concurrency cancels superseded runs on the same branch/PR without changing the release gates.

## Pricing evidence

The full deterministic replay on 2026-09-26 used pricing code from `4cc5b23`, the fixed eval set, and no gateway calls:

| Metric | Result |
|---|---|
| Cases / priced / no analog / unreplayable | 250 / 237 / 13 / 0 |
| Coverage | 94.8% |
| Median absolute percentage error | 53.0% |
| Priced cases within ±20% | 23.2% |

Source SHA-256 digests:

- `quotes.csv`: `6ed19d0cf550f3e65f420b676bbc4354c8dfaf05912d1f5f4edefb4bc8b24cfe`
- `evals/evalset.jsonl`: `6fb53d2600a2fa46715c869e1f72f067c92be688b245e3146c3e1a9f7e9a9e3f`

Reproduce from the repository root after dependency installation:

```sh
node -e "require('node:fs').mkdirSync('out', {recursive: true})"
node estimator/node_modules/tsx/dist/cli.mjs evals/run-eval.ts --register quotes.csv --report out/replay.md
```

Keep the generated Markdown/JSON private (`out/` is gitignored); record the commit, source digests, mode, and summary in the PR. The original `evals/report-baseline.*` remains historical evidence, not the current baseline. Cutoff-aware replay excludes future/same-day quotes and dated revisions/outcomes, but unversioned historical edits remain possible and the sample overweights won/recent quotes. It is not a true backtest or a production acceptance threshold. New reports use `summary.jev_configured` instead of `summary.jev`; configured Jev can still fall back on individual provider failures, so the field does not prove every decision used the model.

## Ordered remaining gates

| Priority | Responsible role | Completion evidence |
|---|---|---|
| 1. Restore hosted checks | GitHub organization billing administrator | Correct the account payment/spending restriction, then run both verification jobs successfully on the candidate commit. Do not bypass required checks. |
| 2. Prove the draft-only pilot | Client owner and host operator | Name the request producer and human reviewer; approve private persistent paths; obtain fresh authenticated read-only owner/workspace/checkout observations; run a fixture, restart with a fresh runner, and prove the same job is a duplicate with intact draft/proof/receipt. Measure actual onboarding time. Follow [the operator guide](local-automation.md). |
| 3. Verify the optional database integration | Authorized database operator | Confirm deployed migration state and exercise refresh/vector registration/search/graph behavior in an approved environment using actual extensions. Do not infer live success from test stubs or run a production migration as a verification shortcut. |
| 4. Improve pricing with a controlled experiment | Estimator maintainer and pricing reviewer | Freeze the evaluation inputs, change one retrieval/pricing policy, compare coverage/error/confidence, and inspect regressions before adopting it. No current result authorizes unattended customer delivery. |

One candidate for the pricing experiment is `retrieve.ts`'s `jaccard` helper: it currently divides token intersection by the sum of set sizes, not union size. Changing it alters retrieval scores and must be evaluated as a pricing-policy change, not slipped into execution maintenance. Parallel paid evaluation likewise needs an explicit concurrency/cost budget before activation.

Do not create another worker or enable a schedule merely to make the project appear active. The existing receipt-backed worker is the execution boundary; use one approved scheduler and preserve its state. No source re-extraction, paid model call, production write, live automation activation, or customer delivery is part of the offline release checks.
