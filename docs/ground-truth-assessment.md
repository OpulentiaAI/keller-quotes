# Source-bound assessment and completed-quote scoring

Use `python -B scripts/keller-ground-truth.py` in an approved private operator environment. `assess` reconciles the frozen all-case audit against supplied original bytes and produces a bounded remediation queue. `decisions` delegates to the separate `evals/decision-eval.py` evaluator for actual full-RFQ attempts. Neither command invokes the estimator, a provider, a database, production tools, or a delivery channel. Neither rewrites targets, registers, historical grades, or controller baselines.

Choose the measurement before running it:

| Question | Executable and source |
|---|---|
| What does each historical target actually establish, and what evidence is missing? | `keller-ground-truth.py assess`, with original calculation/PDF bytes and the independent private audit. |
| Does pricing still pass the unchanged historical ±20% regression? | Existing `evals/run-eval.ts` and `evals/compare.ts`, with identical frozen inputs and source basis. |
| Was a usable, independently supported full quote completed? | `keller-ground-truth.py decisions`, with predeclared eligibility, actual execution/artifacts and independent source-bound review. |
| Does a synthetic order satisfy its fixture? | Existing `evals/run-orders.ts`; this is a synthetic workflow check, not client quote accuracy. |

## Private filesystem and publication

Every path is explicitly supplied. There is no default environment root, automatic source discovery, embedded-audit-path fallback, or production binding. Inputs must be canonical absolute paths outside the checkout, owned by the current Unix user, single-link regular files, mode `0400` or `0600`, with an immediate owner-private `0700` parent. All ancestors must be nonsymlinked, owned by that user or root, and not group/other writable. Symlinks, hardlinks, aliases, duplicate JSON keys, nonfinite numbers, oversized files and recognizable credentials are rejected. Reads have before/after file identity checks. Individual files are bounded at 64 MiB.

`out` names a **new** directory under an existing `0700` parent; it cannot alias or contain an input. The tool creates a `0700` directory and exclusively writes `0400` files through its directory handle. It never replaces an output. Preserve an interrupted or failed bundle and use a new versioned output name. Do not chmod or rewrite client originals merely to satisfy a tool: prepare approved private, single-link copies and verify their hashes instead.

An assessment bundle contains `assessment.private.json`, a count/dimensionless-error-only `aggregate.json`, and `seal.json` with input/output hashes. Decision bundles use `decisions.private.json` instead. The private assessment contains every frozen case, original target, original diagnostic result, source references, full amounts, signed/magnitude errors, unsupported claims and remediation membership. **Never publish it, the config, seal, client sources, queue or source-bound review files, and never give them to blinded quote workers.** CLI stdout is aggregate-only and never authorizes customer release. A seal binds bytes; it is not a digital signature, authenticated issuer identity, WORM storage, or proof that a private owner cannot rewrite an entire bundle.

Exit `0` means a versioned assessment was written, including its unsupported/failed cases; it is not an all-pass or truth-certification code. Exit `2` means configuration or input validation failed. Inspect the private case states before claiming any source coverage or completion.

## Assess the existing all-case private audit

Create a private config with these exact fields. Artifact references are `{ "path": "/absolute/private/file", "sha256": "lowercase SHA256 of the complete original bytes" }`.

```json
{
  "schema_version": 1,
  "as_of": "2026-10-04",
  "expected_cases": 250,
  "evalset": {"path": "/home/operator/private/frozen-evalset.jsonl", "sha256": "..."},
  "bindings": {"path": "/home/operator/private/audit/source/case-bindings.csv", "sha256": "..."},
  "raw_bindings": {"path": "/home/operator/private/audit/source/raw-selected-bindings.json", "sha256": "..."},
  "documents": {"path": "/home/operator/private/audit/source/document-proof.json", "sha256": "..."},
  "source_manifest": {"path": "/home/operator/private/audit/source/input-manifest.json", "sha256": "..."},
  "candidate_report": {"path": "/home/operator/private/unchanged-candidate.json", "sha256": "..."},
  "source_paths": {
    "QUOTEN.DBF": "/home/operator/private/originals/QUOTEN.DBF",
    "QUOTQTYS.DBF": "/home/operator/private/originals/QUOTQTYS.DBF"
  },
  "confirmed_evidence": [],
  "max_queue": 10,
  "out": "/home/operator/private/assessment-v1"
}
```

```sh
python -B scripts/keller-ground-truth.py assess --config "$PRIVATE_ASSESSMENT_CONFIG"
```

Use the actual transferred audit's hashes, not the illustrative ellipses. The `evalset` and `candidate_report` digests must also equal `input-manifest.json`'s `frozen_evalset` and `candidate_report` pins. Copy the unchanged `evals/evalset.jsonl` privately rather than supplying a checkout path. A shortened evalset, duplicated case ID, extra binding ID, changed candidate identity or duplicate result cannot silently redefine the population. Missing bindings/results stay in the all-case output. The original report is retained and annotated, not rescored; the historical ±20% criterion stays unchanged.

`source_paths` maps **exact logical names in `manifest.inputs`** to explicitly approved current paths. Bind the original `QUOTEN`, `QUOTQTYS`, `QUOTLETT`, `QUOTLINE` and `QUOTLEIT` DBFs. For each selected document, include the manifest entries whose hashes equal its `source_pdf_sha256` and `source_transcript_sha256`. The program matches those hashes only among explicitly supplied entries, never follows `manifest.inputs[*].path` or `document.layout_path`, and recomputes complete hashes/sizes. FPT/memo, history and other audit inputs can be supplied and retained, but memo contents and posted-history outcomes are not promoted. Only the declared price/identity fields are decoded; uninterpreted DBF fields are not invented facts.

The original-source reader reopens the pinned DBF bytes, checks physical record index/offset/deletion flag/record digest/raw field bytes, and compares quote/item/customer/part/description/date/revision/drawing/quantity/delivery and `UNIT_SELL` against the frozen case. Document verification independently runs bounded local `pdftotext -layout` on the pinned original PDF, rechecks its layout hash and transcript hash, verifies printed and source identities, and reconciles the complete source curve using full precision, truncated displayed unit price and cent-rounded extension. A selected document with a different letter or revision can establish a separately recorded amount but cannot become direct target proof. Later/conflicting inquiry/footer/revision dates remain blockers. Missing or incompatible source bytes produce explicit `UNVERIFIED` cases and exact expected references; this means unavailable **for this execution**, not absent from the client environment.

Printed/source part comparison collapses repeated layout whitespace only; it preserves punctuation and the original customer/part namespace. An empty or `-` printed revision can represent an actually absent source revision. The report retains `ABSENT_IN_SOURCE`, not a newly inferred revision; stronger manufacturing/current-cost claims still require a known nonplaceholder revision and drawing.

The six domains never collapse into one editable `ground_truth: true` flag:

- `internal_calculation` can be `VERIFIED_SOURCE_BYTES` for `QUOTQTYS.UNIT_SELL`. Internal cost/markup fields do not establish actual cost; currency/UOM absent from the original remain unspecified.
- `recorded_customer_quote` can be `VERIFIED_RECORDED_AMOUNT`. Customer-ID linkage, printed-name prefix limitations, full price/extension, quantity, letter/revision comparability and chronology are separate fields. It never proves acceptance, optimum, actual cost, current support or original historical availability. Its automatic `as_of_eligible` is false: consistent dates and archival mtime are insufficient proof.
- `independently_confirmed_acceptance`, `actual_manufacturing_cost` and `supported_current_quote` require additional independently inspectable source records. An operator assertion has the distinct state `OPERATOR_ASSERTION_NOT_INDEPENDENT_TRUTH`; source-byte checks cannot authenticate its author or turn it into independent evidence.
- `optimum_business_outcome` remains unsupported. This tool has no paired cost/profit/outcome study and cannot certify superiority.

The queue contains at most ten stable work items with affected case IDs, precise missing inputs, a finite attempt budget and unchanged acceptance criteria. Excess groups remain explicitly deferred in the same private assessment, and every case retains its full reason list. This is a work queue, not proof that remediation ran, knowledge promotion, or permission for another parameter sweep.

## Add newly inspected source records without trusting narratives

An optional `confirmed_evidence` item is `{case_id, domain, authority, evidence}`. `domain` is one of the three stronger domains above; `authority` is `source_record` or `operator_assertion`; `evidence` is `{source: {path,sha256}, pointer: ""}` or an RFC-6901 pointer into an independently approved original JSON export. The v1 tool does **not** infer acceptance or actual costs from invoices, filenames, PDF prose, quote-history flags, model explanations or arbitrary operator teaching. When the primary evidence is a PDF or other unsupported format, retain it and obtain independently reviewed structured records with that provenance; do not relabel an operator-authored paraphrase as the original source.

Every financial source record needs `record_id`, `issuer`, timezone-qualified `recorded_at`, `identity` and `amount`. Identity includes exact `quote_no`, `item_no`, `customer_id`, `part_no`, nonblank `revision`/`drawing_no`, positive integer `quantity`, explicit `currency` and `uom`. Amount has decimal-string `unit_price` (up to five places) and cent `extension`; quantity times the full unit must reconcile. Later-than-as-of records, incompatible identity/UOM/currency, wrong extension and conflicting evidence fail closed.

Recognized source kinds and their additional requirements are:

| Domain | Primary record contract |
|---|---|
| Acceptance | `kind: customer_order_acceptance`, `event: customer_accepted_order`, `amount_basis: accepted_order`, and an actual `customer_order_no`. A posted `won` label is not this record. |
| Actual cost | `kind: actual_job_cost`, `amount_basis: actual_closed_job`, actual `job_no`, and cent-total `components` for material/labor/outside/setup whose sum equals the extension. An estimate or stored `UNIT_COST` is not this record. |
| Supported current quote | `kind: supported_current_quote`, `amount_basis: current_supported_quote`, valid-from/until dates, exact `manufacturing` material/finish/routing/tolerances, all four `costs`, and gross `margin_pct`. Each cost has a separately hashed/pointer-bound `current_cost_observation` record, its own record ID/issuer/time/validity, the full identity/currency/UOM, `amount`, `extension`, component and `per_unit` basis (`job_total` for setup). Zero still needs explicit evidence. Components/extensions and the cost-plus unit must reconcile using the source's `unit_precision` of four or five places (default four, matching the existing order contract); retained source amounts are never truncated. |

Records remain explicitly labeled `SOURCE_BOUND_INDEPENDENTLY_INSPECTABLE_RECORD` with `EXTERNAL_SOURCE_APPROVAL_REQUIRED`. This means the named, approved primary bytes can be independently inspected, not that a local file's kind string cryptographically proves customer authorship. Originals must remain available and unchanged; no assertion, review or knowledge-store activation bypasses source authenticity approval.

## Score actual completed quote attempts separately

```sh
python -B scripts/keller-ground-truth.py decisions --config "$PRIVATE_DECISION_CONFIG"
```

The exact config is `{schema_version:1, challenge, assessment, ledger, artifacts, out}`; the four inputs are hashed private artifact references. The assessment must have the schema above, and all its successfully verified original input hashes are reopened. Missing assessment cases cannot become supported prices.

Freeze a `frozen_full_rfq_challenge` before execution, with `schema_version:1`, timezone-qualified `frozen_at`, a `cohort` of `exposed_diagnostic`, `synthetic` or `independent_live`, and all `cases`. Each case binds `id`, predeclared `cohort` (`eligible_quote`, `predeclared_blocked`, `excluded`), original `request`, complete `requirements`, `assessment_case_id`, named `review_assignment`, and exact `allowed_sources`. A blocked case additionally binds independent `blocked_evidence` adjudicated before the freeze. A later output cannot change cohort membership. `allowed_sources` is the frozen worker-visible byte allowlist, not the assessment or hidden adjudication price; actual source-read events must stay within it.

`requirements` is a `full_rfq_requirements` record with `schema_version:1`, `case_id`, quote date, customer ID, currency, **every ordered line**, and full terms. Each line binds stable line ID, full identity/currency/UOM/quantity/revision/drawing, exact manufacturing material/finish/routing/tolerances, and a separately source-bound `manufacturing_specification`. A line can explicitly name its own `assessment_case_id` for a multi-line RFQ; otherwise the case's assessment ID applies. Terms specify payment terms, validity date, positive lead-time days, explicit shipping/tax and every additional charge. Missing manufacturing or terms cannot be fixed with an editable eligibility flag.

Every supplied request `revision`/`rev` and plain `drawing_no`/`drawing_ref` must match the independent full identity, even when the request and draft repeat the same wrong value. A drawing asset path is not an asserted drawing ID. For a path/file reference, the line additionally freezes `drawing_asset: {request_ref, source: {path,sha256}, drawing_no, revision}`. The original independent manufacturing specification must contain that exact binding, the actual approved asset bytes must hash correctly, and the execution trace must include its frozen read-only source hash. Relative customer filenames are retained as `request_ref` only; the evaluator never resolves or opens them implicitly.

The sealed execution ledger has `kind: sealed_execution_ledger`, `schema_version:1`, challenge hash, `sealed_at`, and **every** actual attempt. An attempt contains case/attempt ID, producer ID, `COMPLETED|HELD|ERROR|TIMED_OUT|INVALID`, start/finish times and a pointer-bound `workflow_execution_receipt` matching those values and the raw request/trace/draft/price-decision hashes. The receipt is an independently inspectable execution record, not the model's final claim. Freeze actual eligibility before the first recorded start. Seal the complete producer ledger before independent review. If no attempt exists for a nonexcluded frozen case, the scorer creates a `MISSING_ATTEMPT` failure rather than shrinking the denominator.

The artifacts manifest has `kind: sealed_quote_artifacts`, schema version, ledger hash and observed attempts. Each binds `case_id`, `attempt_id`, raw `trace`, `draft`, `price_decisions`, independent `review`, pointer-bound `review_receipt`, and pointer-bound `handoff`. Missing, duplicated, dropped, orphaned, malformed, held, errored and timed-out attempts remain visible. Even invalid artifacts' raw bytes are hash-checked where supplied; their references/integrity dispositions remain private. Every eligible attempt counts; reruns do not erase failed attempts.

The draft is the real persisted order artifact, not a reconstructed judge answer. Its embedded request, semantic request hash, stable ordered lines, quantities, prices, extensions, subtotal, charges, total and human-review state must reconcile. The price-decision artifact binds case ID/raw request hash/raw draft hash, every ordered `pricing_decisions` line, exact proposed amount, `NUMERIC_PROVISIONAL`, its independently source-bound `supported_quote` record, manufacturing assumptions, complete terms and uncertainties. A finite historical/operator proposal without independently adjudicated current support **fails completion**, even when a reviewer likes its narrative.

The draft provenance hash follows the existing estimator's exact `JSON.stringify(order.request)` contract, not Python's Decimal-to-string serialization or a replacement canonical JSON convention. The evaluator hashes the retained embedded request using a bounded, credential-isolated local Node process; fractional numeric charges/prices remain JSON numbers, and Node's number/property-order/Unicode serialization is preserved. Raw request-byte hashes in the challenge, execution/review receipts and price decisions stay separate and unchanged. Node is required for this compatibility check; it makes no provider or production calls.

The `quote_workflow_trace` binds schema, case/attempt/producer/raw-request hash and contiguous ordered events inside the recorded execution window. `source_read` events bind actual read-only source hashes; required manufacturing/cost reads must exist. `draft_persisted` events bind each actual persisted proposal; `price_decision_persisted` binds the final decisions. The evaluator computes signed unit/extension, absolute and relative error for each observed proposal, separately against compatible internal-calculation and recorded-customer-price references. Missing/invalid proposals stay null, with explicit states, never zero. Proposal means and sample variance are separate diagnostic distributions, not independent-job completion or live accuracy. `independent_live` also requires source-bound read-only Polygres and Ars Umbris typed-runtime capability receipts/results; fabricated capability labels alone fail.

Independent review is not a `{reviewer, passed:true}` field. Freeze a source-bound `independent_review_assignment` with named reviewer, separate executor, case, time and `human_source_review|separate_blinded_review_job` method. Neither named identity may equal the producer. Retain the actual `independent_quote_review` and a separately pointer-bound `independent_review_execution` receipt: assignment, case/attempt, reviewer/executor/job identity, every request/assessment/trace/draft/decision hash, and actual review start/finish after the producer finishes must match. Each required review criterion has a `PASS|FAIL` verdict, reason and independently inspectable source findings with matching identity/as-of. No self-review, missing receipt, forged Boolean approval, missing criterion, unsupported narrative or source conflict passes. Identity strings and local receipts still require external authenticity/independence approval; this is not software authentication of a human or proof of a separate model context.

All eight criteria must pass: identity, source fitness/as-of, manufacturing, cost/price/extension arithmetic, completeness/terms, actual trace integrity, independent review and human handoff. A `human_handoff_receipt` binds the named reviewer, actual received time, private internal channel, request/draft/review hashes; approval is for internal human handoff, never customer release. Mechanical failures cannot be canceled by review passes. Correct `BLOCKED` outputs on predeclared cases require independently reviewed `safe_hold` evidence and are counted only in the separate safety result, never the completed-quote numerator.

Current cost support must be valid both at the declared quote date and the actual attempt finish date; human handoff follows completed review and stays within quote validity. Explicit request material/finish/drawing and shipping/tax/additional charges must agree with the frozen specifications/terms and the actual draft. A reviewer cannot waive those conflicts with a pass label.

The numeric completion rate describes only the supplied, retained attempts. `live_90pct_goal` always remains `NOT_ESTABLISHED_REQUIRES_EXTERNAL_CONFIRMATION`: this exposed remediation diagnostic, synthetic tests, owner-created source/receipt records, or a self-declared live cohort cannot certify blinded isolation, real independent job labels, external authenticity, or the ≥90% release goal. The existing regression tolerance remains `UNCHANGED_20_PERCENT`, and business outperformance is unestablished. Follow the unchanged [decision-quality gates](decision-quality.md) for any real confirmation claim.

Customer-scoped retrieval is not this completion gate. Partial cross-customer description matches may remain provisional historical analogs without exact-part privilege; missing compatibility evidence is not a recorded manufacturing conflict. Those proposals still fail completed-quote scoring without the independent full identity, specifications, current component costs, execution and review records above.

## Local verification

```sh
python -m unittest discover -s scripts/test -p test_keller_ground_truth.py -v
python -m unittest discover -s evals/test -p test_decision_eval.py -v
node scripts/verify.mjs
```

The new source-positive fixtures are synthetic DBFs and real locally extracted synthetic PDFs, never client documents. Tests cover identity/revision/quantity/unit/time/hash/path attacks, unsupported history/cost/assertions, original arithmetic, missing all-case coverage, fabricated review, dropped attempts, separate safety holds and per-proposal signed error/variance. Local validation is evidence of the implementation contract, not a measured client outcome.
