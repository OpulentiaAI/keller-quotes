# Private historical full-data case set

`python -B scripts/keller-full-data-set.py --config "$PRIVATE_FULL_DATA_CONFIG"` builds a separate source-selected historical set. It makes no provider, database, production or delivery calls, does not run the estimator, and never edits registers, frozen evalsets, targets, labels or historical scoring. Exit `0` means a private bundle was written, including an empty eligible set; it does not mean any client case was eligible. Exit `2` means validation failed. Preserve a failed or interrupted output and choose a new versioned directory.

Full data means a historical quote/request, an independently accepted customer order, and a directly linked closed manufacturing job with a complete actual material/labor/outside/setup ledger, matching manufacturing identity, quantity, currency, UOM and chronology. Observing an old closed job does **not** require current-2026 vendor freshness or a business-superiority study. Neither historical evidence completeness nor a synthetic positive certifies current pricing accuracy, live completed-quote accuracy or customer release.

## Fixed binary classifications

Every case has every tag, with an integer `value`, `state`, concrete `reason` and retained `provenance`. `1` means the supplied evidence condition was verified. `0` means **not established**, not a verified negative, lost order, false calculation or confirmed absence in the client environment. Missing, malformed, unsupported and conflicting records remain exclusions with their reasons.

`full_data_eligible` is exactly the AND of these ten required tags. There is no configurable subset or caller override:

| Mandatory tag | Required evidence |
|---|---|
| `internal_calculation_verified` | Reopened pinned QUOTEN/QUOTQTYS physical bytes, identity, quantity and unchanged original target arithmetic. Internal cost fields are not actual cost. |
| `issued_customer_quote_matches_case` | Reverified comparable original PDF/source letter plus a primary send record binding the exact PDF hash, letter, identity, full amount and RFQ. Recorded document comparability alone is insufficient. |
| `full_rfq_verified` | A complete primary RFQ record with every ordered line, manufacturing specification, identity and full terms. |
| `work_order_link_confirmed` | A primary manufacturing work order directly referencing the independently accepted order record and exact order/job identity. |
| `customer_acceptance_confirmed` | A primary customer-accepted-order event, exact issued-quote reference, identity, explicit units/currency and reconciled full amount/extension. |
| `closed_job_actual_cost_complete` | A primary closure, complete enumerated actual ledger postings and component/total reconciliation for the same job; explicit independently sourced zero-component dispositions where needed. |
| `manufacturing_identity_confirmed` | Known nonplaceholder revision/drawing and matching RFQ/job material, finish, routing, tolerances and the same primary specification. |
| `quantity_currency_uom_confirmed` | Exact full identity/quantity and explicit matching currency/UOM across RFQ, issuance, acceptance, job and cost records. Unspecified original calculation currency/UOM are not invented. |
| `chronology_confirmed` | RFQ/specification at quote time, reconciled document dates, actual send, acceptance, job opening/closure and final cost times in order, all within `as_of`. |
| `independent_source_review_confirmed` | Independently named source review and separate execution receipt binding all required condition findings and reopened primary/source hashes. Mechanical source checks cannot be waived. |

Five optional tags never gate membership: `recorded_customer_amount_verified`, `work_order_candidate_present`, `current_quote_support_verified`, `business_optimum_verified` and `erp_quote_work_order_pointer_verified`. Current support uses the existing current-cost/quote helper at `as_of`, not as a historical membership prerequisite. Business optimum is always `0` with an explicit unsupported reason in v1; no paired cost/profit/outcome study is implemented. A native ERP pointer tag is a quote-level stored-foreign-key observation only, never acceptance or manufacturing/quantity equivalence.

The original-source build on 2026-10-04 retained all 250 cases: **0 eligible and 250 excluded**. It reverified all 250 internal calculations, 107 recorded customer amounts (105 target-comparable), 853 distinct physical WOHEAD candidates across 102 cases, and 954 four-table native pointer chains across 99 cases, with no rejected candidate or chain references. It did not establish any of the other nine mandatory conditions. Every original target and exclusion remains in the sealed private audit; zero eligibility is not zero quoting accuracy or evidence that these orders were lost.

Those 105 comparable PDF targets establish **recorded-price comparability**, not authenticated issuance or acceptance; the broader 107 recorded amounts include noncomparable documents. Candidate existence and native pointer equality are not accepted-order or closed-job confirmation. The separate source investigation found only 31 cases with blank quote item, known nonplaceholder matching order/work-order revision and order quantity equal to the target. Neither those limited comparisons nor the 1,981 linked WOBILL rows and 13 WOBOM rows establish acceptance, full manufacturing identity or complete actual ledgers. Synthetic implementation tests separately exercise mechanical validation, not client business outcomes or source authenticity.

Selection uses source availability and confirmation only. Predicted prices, model criteria, errors and successes never enter a tag or eligibility predicate. The source assessment retains the unchanged candidate report for audit compatibility, but the builder ignores its scores. The original assessment config's `confirmed_evidence` is ignored; its editable domain assertions cannot promote a tag. Assessment JSON states from an earlier run are never trusted as input: the original pinned inputs and approved originals are reopened with the existing `assess` implementation.

## Private config and supplementary confirmations

All artifact references are `{ "path": "/absolute/private/file", "sha256": "lowercase whole-file SHA256" }`. All paths obey the [existing private filesystem contract](ground-truth-assessment.md#private-filesystem-and-publication): canonical owner-private files outside Git, mode `0400` or `0600`, single-link regular files under an owner-private `0700` parent, safe nonsymlinked ancestors, explicit paths and unchanged hashes. The original assessment, JSON, PDF, candidate and other source reads keep their unchanged 64 MiB bound. Only the fixed four-table native-order-chain reader below allows 128 MiB per original table, needed for the supplied SOMAST file (90,049,986 bytes). Inputs are rechecked before publication at their same declared limits. Do not chmod client originals to satisfy these rules; prepare approved private copies with matching hashes.

```json
{
  "schema_version": 1,
  "as_of": "2026-10-04",
  "assessment_config": {"path": "/home/operator/private/assessment-config.json", "sha256": "..."},
  "confirmations": {"path": "/home/operator/private/confirmations.json", "sha256": "..."},
  "out": "/home/operator/private/full-data-v1"
}
```

The pinned assessment config is the original `assess` config, with the unchanged complete evalset/population, case bindings, raw physical bindings, document proofs, input manifest, candidate report and explicitly approved original source paths. Its `as_of` must match. The builder replaces only its output path and removes its `confirmed_evidence`; it writes a freshly reopened assessment inside the new bundle. There is no source discovery, input shortening, silent population replacement or external-system access.

The supplementary file has exactly `{schema_version:1, kind:"historical_full_data_confirmations", prepared_by?, cases}`. `prepared_by` is required for a positive independent-review tag, but native-only supplements may omit it. Each case has `case_id` plus any available `rfq`, `issuance`, `acceptance`, `work_order`, `actual_cost`, `current_quote`, `review`, `review_receipt`, `candidate` and `native_order_chains` fields. Omit unavailable fields. Duplicate or undeclared case IDs and extra case/config fields are rejected. Every field except `candidate` and `native_order_chains` is `{source:{path,sha256},pointer}` into an independently approved primary JSON record, using the existing RFC-6901 pointer helper. These are not tag flags or an operator-authored reconstruction relabeled as an original export. Missing original structured records or unsupported original formats stay unestablished; v1 adds no general ingestion or ERP semantic interpretation beyond the exact native foreign-key checks below.

### Original WOHEAD candidates

`candidate` is a list of physical references, not a count or narrative:

```json
{
  "case_id": "0000001|@10",
  "candidate": [{
    "source": {"path": "/home/operator/private/WOHEAD.DBF", "sha256": "..."},
    "physical_record": {
      "record_index": 0, "record_no": 1, "byte_offset": 321,
      "record_sha256": "...", "raw_field_hex": {}
    }
  }]
}
```

Use actual original values, never these illustrative offsets. `raw_field_hex` is optional; if supplied, it must cover every original DBF field exactly. The reader requires the explicit source basename `WOHEAD.DBF` (case insensitive), reopens its whole-file hash, validates the physical record index/number/offset/deletion marker/hash and optional raw field bytes through `dbf_record`, and matches exact `COMP_ID`/`PART_NO` against the reconstructed assessment identity. Records deduplicate by source hash and physical index, per case and across the manifest. Rejected references remain in the audit. One verified candidate can establish existence even when another candidate reference fails; the failures stay visible.

All decoded fields are retained as observations. Revision/quantity comparisons, PO-looking strings, shipment existence, posted `QUOTHIST won`, cost-looking field names and stored calculated costs do not establish acceptance, direct quote/order linkage or complete actual cost. Candidate evidence is optional and never substitutes for a required structured primary record. This candidate adapter only interprets WOHEAD identity; the separate native pointer classification remains equally nongating.

### Quote-level native ERP pointers

`native_order_chains` is a per-case list of `{sales_order,sales_lot,work_order,work_order_job}`. Every entry is the same `{source,physical_record}` original DBF receipt used above, not a narrative, assertion or reconstructed JSON source. The role fixes the required basename (case insensitive): `sales_order` → `SOMAST.DBF`, `sales_lot` → `SOLOTS.DBF`, `work_order` → `WOHEAD.DBF`, `work_order_job` → `WOJOBS.DBF`. All four whole-file and physical receipt hashes, record index/number/offset/deletion marker and optional raw field bytes are checked through the existing private reader and `dbf_record` protections.

A verified chain requires exact stored equalities:

1. SOMAST `QUOTE_NO`/`COMP_ID`/`PART_NO` equal the reconstructed assessment quote/customer/part.
2. Nonblank `JOBNO` matches in SOMAST, SOLOTS and WOJOBS; SOLOTS `COMP_ID` equals the same customer.
3. Nonblank `WO_NO` matches in SOLOTS, WOHEAD and WOJOBS; WOHEAD `COMP_ID`/`PART_NO` equal the same customer/part.
4. Nonblank `LOT` matches in SOLOTS and WOJOBS.

One valid chain gives `erp_quote_work_order_pointer_verified:1` with state **`QUOTE_LEVEL_ERP_POINTER_ONLY`**. It does not set `work_order_link_confirmed`, `customer_acceptance_confirmed`, manufacturing identity, quantity/currency/UOM or complete actual cost. Quote item, revision, quantity, drawing, acceptance event and ledger completeness remain unresolved; source fields are retained observations, not additional ERP interpretations. The structured accepted-chain and ten-tag AND remain unchanged. All rejected alternatives and their failed relationship/source reasons remain in the audit, even when another chain verifies. Chains deduplicate by the four source hashes and physical record indices, per case and across the population; total supplied chains must be at most 10,000.

The 128 MiB allowance exists only for these four fixed native-chain table roles in this builder. Whole original bytes are cached only after hash verification; repeated chains do not reread whole files. Native input pins are tracked separately, rehashed using that same narrow bound immediately before publication, and merged into manifest/seal inputs with pin-conflict and output-alias checks. Neither the existing helper nor another source reader gains a larger limit. Native records and pointer observations are post-quote operator-only target evidence, never worker context.

### Structured historical primary records

Each primary record has `kind`, `record_id`, `issuer`, timezone-qualified `recorded_at` and full `identity`. Identity uses exact `quote_no`, `item_no`, `customer_id`, `part_no`, known nonplaceholder `revision`/`drawing_no`, positive integer `quantity`, explicit `currency` and `uom`. `agent`, `operator` and the named preparer are not accepted primary issuers. Kind/issuer strings alone do not prove authenticity; externally approved original primary bytes and independent review are still necessary.

The deliberately narrow supported record contracts are:

- `full_rfq_requirements` has `schema_version:1`, `case_id`, original `quote_date`, `customer_id`, `currency`, every ordered `lines` entry and `terms`. Each line has `line_id`, full `identity`, `manufacturing` (`material`, `finish`, `routing`, `tolerances`) and a bound `manufacturing_evidence` record of kind `manufacturing_specification`. A drawing asset, when supplied, is the existing `{request_ref,source,drawing_no,revision}` binding repeated in that specification, and its original bytes are reopened. Terms contain `payment_terms`, `valid_until`, positive integer `lead_time_days`, explicit cent `shipping`/`tax` and all `additional_charges` (`description`, cent `amount`). Exactly one complete line matches the original case identity/quantity. All other ordered lines are validated too.
- `customer_quote_issuance` has `event:customer_quote_sent`, the exact `letter`, `document_sha256`, bound `rfq` reference and `amount:{unit_price,extension}` matching the reverified full customer-PDF amount. `recorded_at` must be the actual send-event time, not archival mtime or later entry time. The comparable PDF is not itself this send record.
- `customer_order_acceptance` uses the existing financial helper's `event:customer_accepted_order`, `customer_order_no`, `amount_basis:accepted_order` and reconciled `amount`, plus the exact bound `issued_quote` reference. A PO number alone or won history cannot replace the primary event. Accepted amount remains a separate observed amount; it does not replace or require numerical equality with the internal-calculation target.
- `manufacturing_work_order` has `job_no`, `opened_at`, exact `customer_order_no`, a bound `acceptance` reference, complete `manufacturing` and the same bound `manufacturing_evidence` as the matching RFQ line. This is a primary directly linked job record, not a WOHEAD candidate or a derived case-link assertion.
- `actual_job_cost` uses the existing helper's `amount_basis:actual_closed_job`, `job_no`, reconciled full `amount` and cent `components` for material/labor/outside/setup, plus bound `work_order`, `closure`, timezone-qualified `period_start`/`period_end`, all `postings` and explicit `zero_components`. Its final full-unit amount/extension and all component totals must reconcile; an estimated or partial ledger fails.

`closure` is a primary `manufacturing_job_closure` with `event:manufacturing_job_closed`, exact `job_no`/`work_order`, `closed_at`, the ledger period, component totals and the complete `posting_record_ids` enumeration. Every posting is a bound primary `actual_job_cost_posting` with full identity, exact job, component, `basis:job_total`, positive cent `amount` and `incurred_at`. No duplicate ID or physical source/pointer can count twice. Posting IDs must exactly match the closure enumeration, all incurred times lie within the opened/closed job and every posted time precedes the final ledger. All four sums equal both closure and financial-record components. Signed/reversal/unsupported posting formats must remain exclusions, not be silently netted or reconstructed.

Each zero component has `{component,evidence}` pointing to a primary `closed_job_zero_cost_component` with the same identity/job/closure/period, `basis:job_total`, explicit zero `amount`, recorded time after closure and a concrete `reason`. Exactly the zero-total components need these dispositions; missing, extra and duplicate dispositions fail. A component name, absent posting or numeric zero alone is not evidence of ledger completeness. Completeness depends on externally approved primary closure/ledger enumeration, not a caller's `complete:true` field.

### Independent source review

`review` and `review_receipt` are separate bound records, avoiding a circular hash. A `historical_full_data_source_review` has the primary record fields, `case_id`, named `reviewer_id` and `executor_id` distinct from `prepared_by`, actual `started_at`/`finished_at` after the source records, and exactly one `findings` entry for each of the first nine mandatory conditions. Every finding has `condition`, `verdict:VERIFIED`, a concrete `reason`, full matching `identity` and `sources`. A negative/unestablished finding fails review; a verified verdict cannot waive any mechanical condition. `sources` is the sorted, deduplicated list of `{path,sha256}` artifacts in that condition's audit provenance, including nested specification/drawing/ledger originals. Every hash is independently reopened; `passed:true`, self-review and unsupported narrative cannot replace source checks.

The `historical_full_data_review_execution` receipt binds `case_id`, whole `review_source_sha256`, the same reviewer/executor and start/finish times, a real `review_job_id` and the sorted deduplicated union of all finding `sources`. The original independent review workflow must supply both records; do not fabricate them to obtain a positive tag. Naming identities and matching local receipts are supplied provenance, **not cryptographic human authentication or proof of separate context**. External authenticity/independence approval remains necessary, just as for the existing helper. A seal binds bytes, not trustworthy authorship, WORM storage or immunity to rewriting the entire bundle.

## Outputs and evidence roles

`out` must be a new directory under an existing owner-private `0700` parent outside Git. Publication creates `0700` directories and exclusively writes `0400` files; it never overwrites a version. The bundle contains:

- `all-case-tags.private.json` and `all-case-tags.private.csv`, retaining every case's required/optional binary tags and their states/reasons/provenance. JSON additionally holds `original_target`, actual source observations, candidate/chain rejections and concrete exclusions. CSV is tag-focused and contains no original target or price columns; eligible/excluded JSONL retain the original case content and targets.
- `eligible-historical-cases.jsonl`, copying each eligible original frozen case line unchanged, with every original target and original case shape. No acceptance, job, actual-cost or later source field is injected. An empty file is valid.
- `excluded-cases.private.jsonl`, retaining every excluded original case and its required-tag reasons. Unsupported evidence is not translated into a false business outcome.
- `manifest.json` and `seal.json`, recording fixed semantics, population/counts, original-case-ID digest, eligibility predicate, merged original/native input pins and implementation hashes, source limits, output hashes and limitations.
- `reopened-assessment/`, the freshly executed private original-source assessment and its existing aggregate/seal, without trusting earlier domain flags.

The entire bundle is **operator-only**, including the eligible JSONL because it retains hidden original targets. A blinded worker may receive only approved quote-time input fields and source bytes through the existing frozen allowlist, never tags, manifests, acceptance, future manufacturing costs, review records or target values. RFQ/specification references are labeled quote-time inputs; send/acceptance/job/cost/review references are post-quote operator-only target evidence. This tool generates no worker context and does not change an existing worker allowlist. Historical targets remain internal calculations, not automatically accepted prices or actual-cost targets.

Stdout contains counts only, never case IDs, amounts, customer/part details, file paths or hashes. Preserve source-authenticity uncertainty and every excluded case in the private audit, even when the eligible count is zero.

## Local verification

The builder adds no Python package dependency; original PDF verification reuses the declared local `pdftotext` prerequisite. The synthetic fixtures create real PDFs and DBFs locally and never call source systems or providers. Run:

```sh
python -B -m unittest discover -s scripts/test -p test_keller_full_data_set.py -v
python -B -m unittest discover -s scripts/test -p test_keller_ground_truth.py -v
node scripts/verify.mjs
```

`verify.mjs` includes the new focused suite. It works under `umask 022`; precreate an owner-private log directory and open redirected log files privately rather than relying on the ambient umask. Tests cover an empty set, a synthetic 250-case/102-candidate/853-physical-record population, candidate deduplication/hash/identity attacks, exact original-case preservation, positive historical chains without current support, partial/duplicate/open/estimated/zero-component ledgers, identity/UOM/manufacturing/time conflicts, source-bound independent review, score independence, fixed predicates, private modes and reproducible seals. Native-pointer regressions exercise the exact four-table joins, incorrect JOBNO/customer/LOT/work-order/quote/source/physical hashes, deduplication, whole-file caching, retained rejected alternatives, the unchanged 64 MiB default, native-only 128 MiB bound and prepublication rehashing. Synthetic positives test mechanical validation, not real primary-source authenticity or client business outcomes.
