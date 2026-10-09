# Keller deterministic diagnostic controller

`scripts/keller-improvement.mjs` freezes inputs, runs the **real** `evals/run-eval.ts`, runs the **real** `evals/compare.ts --fail-on-regression`, and builds a bounded next-work queue. It doesn't implement another estimator, select new pricing parameters, change the rubric, promote skills, query a database, or release customer quotes.

Pipeline verification, diagnostic nonregression, and the **>90% independent live completed-quoting goal** are separate results. The controller always reports `independent_live_accuracy: "NOT_ESTABLISHED"` and `goal_over_90_percent: "UNMET"`. Offline historical replay cannot establish that goal, even if every diagnostic case passes. The fixed evalset, its development/holdout slices, and previously exposed PDFs are never blind confirmation. See [decision quality](decision-quality.md) and [private trajectory analysis](mcp-trajectory-analysis.md).

## Prerequisites and private storage

Use Node 24 or newer and install the existing estimator dependencies with `(cd estimator && npm ci)`. The controller itself imports only Node builtins. Supply an **absolute canonical, owner-only state directory outside the checkout**. Every existing ancestor must be a nonsymlink directory owned by root or the current UID, without group/other write permission. Symlink roots/ancestors, noncanonical paths, and writable untrusted ancestors (including `/tmp`) are rejected before directory creation. It rejects a directory inside, or containing, the checkout; root permissions must exclude group/other access and match the current UID. New files use mode `0600`, and new directories use `0700`; children inherit umask `077`, including the real runner's reports. Artifact verification checks owner-only permissions as well as hashes.

The register, evalset, and existing baseline must be explicit absolute regular-file paths. Reports with real customer values remain private. Neither `quotes.csv` nor the checked-in legacy baseline is implicitly selected. The baseline must be a real schema-v2 report from the same register, evalset, selected identities, targets, and effective cutoff-aware/offline configuration. A source-code difference is allowed; a register change is not a matched code experiment. The real comparator validates the full baseline and candidate, including criteria, summaries, slices, arithmetic, and provenance.

## CLI

Each command accepts one JSON object on stdin, or `--config /absolute/config.json`. Stdout is exactly one JSON result, without runner logs or customer prices. Exit status is `0` for normal results, `1` for failure/invalidation/regression, and `3` for a busy execution lock. Logs and per-case artifacts stay in private state. Don't publish the entire state directory.

Create a configuration outside the checkout, replacing these paths with approved inputs:

```json
{
  "state_root": "/home/operator/private/keller-improvement",
  "register": "/home/operator/private/verified-register.csv",
  "evalset": "/workspace/keller-quotes/evals/evalset.jsonl",
  "baseline": "/home/operator/private/current-guard-report.json",
  "cohort_kind": "diagnostic",
  "selection": {},
  "command_timeout_ms": 120000,
  "total_timeout_ms": 300000
}
```

```sh
node scripts/keller-improvement.mjs freeze --config /home/operator/private/freeze.json
printf '%s\n' '{"state_root":"/home/operator/private/keller-improvement","job_key":"SHA256_FROM_FREEZE"}' \
  | node scripts/keller-improvement.mjs run
printf '%s\n' '{"state_root":"/home/operator/private/keller-improvement","job_key":"SHA256_FROM_FREEZE"}' \
  | node scripts/keller-improvement.mjs status
```

`freeze` returns `{state, duplicate, job_key, plan_path}`. Unknown configuration fields are rejected, including proposed live-accuracy claims. `cohort_kind` can only be `"diagnostic"`; there is no confirmation mode or Jev/retrospective override.

Configuration options:

| Field | Contract |
|---|---|
| `state_root` | Required absolute owner-private directory outside the checkout. |
| `repo_root` | Optional absolute checkout root; defaults to this script's checkout. Commands and inventories are fixed relative to it, not caller-supplied executable overrides. |
| `register`, `evalset`, `baseline` | Required absolute input files. |
| `selection` | Defaults to `{}`: **all cases**. Alternatively `{ "limit": N }` or `{ "sample": N, "seed": "explicit-seed" }`. A sample requires an explicit nonempty seed and a matching baseline. |
| `max_cases` | Defaults to 250; integer 1–250. Empty selections and selections above the cap are rejected. The default full250 run is supported without changing its effective comparison configuration. |
| `concurrency` | Only `1` is accepted. The entire private state root shares one execution lock. |
| `command_timeout_ms` | Defaults to 120000; integer 1–900000. Each child process group is killed with `SIGKILL` on timeout. |
| `total_timeout_ms` | Defaults to 300000; integer 1–900000. Completed command durations consume this budget across explicit resumes; interrupted commands reserve their full timeout. |
| `max_attempts` | Defaults to 2; integer 1–3, bounding comparison attempts. Failed/interrupted evals aren't automatically repeated. |
| `skills` | Optional array of additional absolute skill files. It **adds to**, rather than replaces, every canonical `.agents/skills/**/SKILL.md`. |

`run` and `status` accept `{state_root, job_key}`. `run` additionally accepts `resume: true` for explicit checkpoint continuation. A successful duplicate rerun verifies current inputs, source inventory, plan/journal bindings, and all recorded artifact checksums before returning `verified_duplicate: true`; it doesn't invoke the estimator again. Missing or changed artifacts aren't a duplicate success.

## Freeze, journal, locking, and recovery

The exact job key hashes normalized configuration, input content hashes, case identity digest, the wider workflow source inventory, canonical and extra skill hashes, the actual controller bytes, Node version/executable hash, and tsx entrypoint hash. The immutable plan is written **before any child execution**. The register, evalset, and baseline are also copied into private frozen input files; the real runner reads those copies. Original and frozen-copy hashes are still rechecked, so changed originals or snapshots invalidate an old plan rather than silently reusing it.

The deterministic source inventory includes estimator sources and lock/config files, evaluation TypeScript, direct workflow scripts, Ars Umbris tools/config/lock declarations, types, profiles, skill pointers, injections, `.arsumbris` declarations, and the decision-quality/trajectory contracts. All canonical `SKILL.md` files are hashed, including newly added skills; caller-supplied extras can't omit them. Inventories cap at 1024 files per category. Generated private payloads, `.keller-local`, `node_modules` trees, PDFs, and historical report files aren't traversed. New or removed eligible files change the inventory. The controller's wider attestation is separate from, and checked alongside, the estimator-only source digest already emitted by the eval runner.

Inputs, sources, skills, and runtime hashes are checked immediately before and after each real command, again before finalization, and during duplicate/status verification. The child environment is a small allowlist with `OFFLINE=1`, `KELLER_OFFLINE=1`, fixed locale/timezone, disabled tsx cache, and private HOME/TMPDIR. It doesn't inherit gateway keys, database URLs/passwords, other credentials, proxy variables, `NODE_OPTIONS`, or preload hooks. The runner receives no `--jev` or `--retrospective` flag. This is credential-isolated offline execution, **not an OS network sandbox or independent live workflow**.

Each journal checkpoint is an exclusive new file with a content-hashed name, sequence number, and previous-checkpoint hash. It binds frozen inputs, command starts/PIDs/results, logs, candidate reports, actual comparison outcomes, diagnosis, and completion. Files aren't replaced and failures aren't removed. The private layout is:

```text
state_root/
  execution.lock
  retired-locks/
  jobs/JOB_SHA256/
    plan.json
    inputs/{register,evalset,baseline}
    journal/000001-CHECKPOINT_SHA256.json
    candidate.{md,json}
    eval-1.{stdout,stderr}
    comparison-N.{md,stdout,stderr}
    diagnostics.private.json
    aggregate.json
    schedule.json
    incidents/
```

The lock is created exclusively and covers all jobs under that state root. A lock is reclaimed only when its owner is a proven-dead PID on the same host. Age never authorizes reclamation. Live, foreign, incomplete, or unknown owners stay busy. An unfinished command additionally requires a recorded, proven-dead child PID/process group before a dead owner's lock can be reclaimed. An interrupted command without a completed checkpoint stays ambiguous and requires operator review; orphan output files aren't adopted as a successful run. Dead lock records are retained.

A failure after `eval_completed` can resume comparison without repeating pricing. Supply `resume: true`; the original failure/log/artifacts remain, and successful continuation reports `COMPLETED_WITH_FAILURE_HISTORY`, not a clean success. Every comparison still passes `--fail-on-regression`, and attempts and remaining timeout budget stay bounded. A genuine comparator regression is recorded as a completed diagnostic `REGRESSION` with its nonzero exit and a retained failure. It isn't retried to seek a favorable result. Changed inputs or code require a new frozen job; never edit a frozen plan to make a run pass.

Artifact integrity failure never overwrites an earlier completion. Status becomes `INVALIDATED`; later failure checkpoints or incidents preserve the problem. Preserve damaged private state for review rather than deleting failures. These are checksum-bound, API-immutable records, not signatures or filesystem WORM storage: a malicious owner who rewrites the entire ledger isn't prevented. Pre/post source checks also cannot attest to an undetected edit-and-restore between checks, original PDF authenticity, external worker isolation, live database access, or independent reviewer judgments.

## Diagnosis and learning queue

Use an existing report without rerunning pricing:

```sh
printf '%s\n' '{"state_root":"/home/operator/private/keller-improvement","report":"/home/operator/private/candidate.json","baseline":"/home/operator/private/baseline.json"}' \
  | node scripts/keller-improvement.mjs diagnose
```

`diagnose` requires schema-v2 **results**, not a baseline summary. It returns a safe aggregate, private diagnostics path, and work queue. Optional `expected_cases` is an array of IDs or eval-case objects; missing results become errors in the all-case denominator. Without that array, a matched baseline supplies missing case identities. An absent/invalid price stays null, never a zero-dollar attempt.

Diagnostics report priced/held/error/missing counts, all-case completion and criterion denominators, priced-only APE, every matched pass-to-fail criterion loss and gain, signed and absolute errors, and paired change distributions. Unit/extension dollar values and per-case reasons remain in `diagnostics.private.json`; `aggregate.json` contains counts, dimensionless price-error distributions, criterion-loss totals, and hashed work IDs, without case IDs, customer/source paths, raw prices, or quoted reasons. Sample variance/stddev are null with fewer than two numeric observations; means and medians are null when no paired observations exist. Paired error changes use only cases with finite comparable prices in both reports, while missing/held/error cases still count in all-case failure statistics.

Work items are based on observed failed criteria: source exclusion/cutoff eligibility, missing/invalid execution or identity, absence of admitted analogs, arithmetic reconciliation, and numeric price misses. Matched criterion losses are prioritized rather than offset by gains. The controller doesn't infer missing geometry, stale vendor costs, model reasoning, or manufacturing causality from price error alone. Such hypotheses need separately observed evidence.

`buildSchedule` returns a maximum of ten dependency-bound work items in this order:

1. Diagnose the sealed run, including every loss and missing attempt.
2. Remediate evidence or draft a scoped skill candidate tied to the observed failures.
3. Perform matched development using unchanged inputs/criteria and the real comparator.
4. Request an untouched, globally isolated **external live** confirmation cohort; this runner cannot execute or certify it.
5. Obtain independent review before any promotion or release claim.

Queue options are `history: [{id,status,attempts}]` (`completed`, `failed`, or `running`), `evidence_ready`, `development_ready`, `confirmation_available`, `reviewer_available`, `max_attempts` (1–3), and `max_items` (5–10). Supply `confirmation_evalset_sha256` and previously `used_evalset_sha256` hashes when proposing a cohort; reuse of this diagnosis's evalset or a declared used set escalates as `USED_SET_CANNOT_CONFIRM`. Availability flags plan operator work; they never certify untouched PDFs, independent confirmation, a judge verdict, or live accuracy. Missing required inputs block work explicitly. A smaller queue cap defers remaining diagnostic work and blocks matched development until that work is reconciled. Exhausted attempts escalate instead of generating another parameter sweep. Review has a single attempt. The queue never modifies files, memory, skills, models, tools, or the rubric, and has no autonomous promotion action. Candidate evidence verification and independent candidate review must precede `development_ready: true`; final independent review doesn't replace those gates.

## Exported API and tests

```js
import { freezePlan, runPlan, diagnoseReport, buildSchedule, statusPlan } from './scripts/keller-improvement.mjs';

const frozen = freezePlan(config);
const run = await runPlan({ state_root: config.state_root, job_key: frozen.job_key });
const diagnosis = diagnoseReport(schemaV2Report, { baseline: schemaV2Baseline, expected_cases: cases });
const schedule = buildSchedule(diagnosis, { evidence_ready: false });
```

`freezePlan`, `diagnoseReport`, `buildSchedule`, and `statusPlan` are synchronous; `runPlan` is asynchronous. The exported diagnosis object includes `private_cases` and `private_numeric_summary` for private operator use; **don't publish that object**. CLI stdout and the persisted aggregate are intentionally narrower. The work queue is planning output, not evidence that those jobs executed.

```sh
node --check scripts/keller-improvement.mjs
node --test scripts/test/keller-improvement.test.mjs
```

Tests use small synthetic CSV/JSONL fixtures through the actual repository eval runner and comparator, with no gateway or database. They cover freezing/default full selection, source/skill/input tampering, private artifact checksums, concurrency, cautious stale-lock handling, explicit comparison-stage resume, retained regressions with actual nonzero comparator exits, hard timeouts, credential removal, missing-case denominators, variance, deterministic bounded queues, and refusal to call a used set confirmation. Synthetic tests verify the pipeline contract, not Keller customer accuracy.
