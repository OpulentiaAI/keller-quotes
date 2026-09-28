# Blinded historical quote workflow evaluations

This is a separate population, `blinded-historical-quote-workflow`, not an update to the exact-reissue rubric or its results. The worker receives a frozen RFQ and application-scoped prior evidence, but **never** the target prices, target documents or oracle. The scope is enforced by the MCP client, not by OS isolation between agents sharing a user account. A human must review every proposed price; a plausible proposal is neither an authorized reissue nor a current-cost, terms, or delivery guarantee.

Keep the original customer PDFs, verified target provenance, private oracle, scope, trace, answer, judgment and report outside Git in owner-private storage. Before freezing a case, separately preflight original target PDFs and their price/extension provenance. Freeze the raw scope bytes and SHA-256 before the worker runs; the client filters future and held-out prices/pages and limits raw-source/file access. The grader independently checks the scope file's private ownership, non-symlink path, hash, eligible rows and exclusion of **all** target quote numbers. Each logged MCP row must carry `evaluation_scope_sha256` equal to the oracle's scope hash. If no admissible analogy exists, hold the case rather than manufacturing a price; held attempts stay in the attempted denominator and cannot all-pass.

## Contracts

Oracle v1 is `{schema_version:1,population:'blinded-historical-quote-workflow',case_id,request,reviewer_identity,targets,scope}`. `request` contains `case_id,order_id,quote_date,customer,customer_id,corpus,reviewer,charges:{shipping,tax},requested_lines:[{line_id,part_no,description,quantity,uom:'pieces',revision,notes}]`. The separate `targets` array maps each requested `line_id` to `quote_no,item_no,quantity,unit_price,extended_price,source_document,source_document_sha256`. Full-precision target units and cent-rounded printed extensions are validated in the oracle, never delivered to the worker. `reviewer_identity` establishes a named human with a nonblank source. `scope` holds an absolute owner-private JSON `path` and SHA-256 of its **raw bytes**.

Scope v1 contains `schema_version,case_id,corpus,quote_date,excluded_quote_nos,request,eligible_prices,allowed_files`. Its request repeats the frozen order/customer/reviewer/date/explicit charges and parts with line IDs, part numbers, quantities. Every eligible row has quote/item identity, quantity, full-precision unit and extension, prior quote/letter/nonblank last-touch dates, part/customer, source price field, `customer_quote_pdf` basis, unknown outcome, source path and PDF/transcript hashes. An `item_no` may be an empty string, but cannot be missing or non-string; distinct quantity breaks under the same quote/item/document remain distinct identities by numeric quantity. The excluded set must contain every target quote number, and none of those numbers can be eligible. `allowed_files` contains only the five canonical Keller skills and the exact public contracts `docs/pricing-evals-and-orders.md`, `estimator/src/order.ts` and `estimator/src/types.ts`. The client restricts exposure; the grader independently checks the returned prices, search hits, pages and every quote response's analog references, including discarded drafts.

The answer is `{case_id,draft,evidence,pricing_decisions,reviewer_handoff,customer_message,unresolved}`. `draft` is the unchanged successful `keller_quote` response or `null` for a held attempt. Each evidence citation names `line_id,quote_no,item_no,part_no,quantity,source_path,pdf_sha256,source_unit_price,source_printed_extension,source_quote_date,rev,admission_reason`. Multiple distinct eligible prior breaks per line are allowed, but a completed priced line needs one or more; duplicate source identities are rejected **within that line**, while the same source may legitimately support different requested lines. The prices result doesn't include `date_stamp` or `rev`: the scope contains the former and the judge independently checks the latter against the page. Each pricing decision names `line_id,method,derivation,uncertainties,proposed_unit_price`; `explicit_unit_price` in an order is the agent's proposed calculation, not operator approval. The judge decides whether that analogy and derivation are defensible.

## Independent criteria

| Mechanical | Requirement |
| --- | --- |
| V1 | Actual canonical quote skill read, verified selected-corpus price retrieval and unique last successful `keller_quote` response equal to `draft`; compare persisted UUID-bound `order.json`, `order.md`, `review.json` against that exact response. Previous distinct drafts remain visible in the trace. |
| V2 | Exact request/order/date/customer/id, line IDs, part numbers, quantities, and explicit shipping/tax, without omissions, additions or extra fees. |
| V3 | Finite positive proposed units inside the unchanged inclusive ±20% guard around independently frozen target units; extensions round proposed unit × requested quantity half-up to cents, with precise subtotal/priced subtotal/total and explicit charges. Target printed extensions are verified in the oracle, **not** required to equal proposed extensions. |
| V4 | Complete finite prices/charges/total and persisted `PRICED_REQUIRES_REVIEW`, pending named human proof, human review required, customer release false and no blockers. |
| V5 | Every audit event scope-bound; no held-out/future returned evidence or reused target document path; all citations distinct within each requested line, scoped and actually observed as verified price rows; correct selected corpus and eligibility for all returned prices, pages, search hits and quote analogs. Successful calls outside the scoped tool/file allowlist and alternate result channels fail; denied null-result retries do not expose data. Numeric coincidence with an oracle target is not itself evidence of leakage. |

| Independent judge | Requirement |
| --- | --- |
| J1 | Substantive intake and complete, accurately interpreted RFQ. |
| J2 | Probative issued-price source evidence and page-checked revision, not snippets/internal/supplier prices or assumed outcomes. |
| J3 | Defensible analog selection, adjustments, precision and uncertainty; no invented current costs. Numerical agreement alone cannot redeem an invalid analogy. |
| J4 | Actionable named-human handoff, explicit charges and unresolved confirmations, with review/release boundary. |
| J5 | Customer-safe pending-review message without private evidence, unsupported terms, lead time or delivery guarantees. Defensible process confirmation is not a commercial guarantee. |

The independent judge receives the full trace and scope evidence, not worker reasoning, prior scores or desired verdicts. Its JSON has `case_id,input_sha256:{oracle,answer,audit},criteria:[{id,verdict,reason,evidence}]`, with exactly one `pass`/`fail`, a nonblank reason and concrete citations for each J1–J5. The three hashes bind **exact raw file bytes**. Keep original verdicts in the main result; document any adjudication separately. Missing, malformed, mismatched or unjudged results fail closed.

Run locally with owner-private inputs and output directory (0700):

```sh
python3 scripts/grade-blinded-mcp-workflow.py \
  --oracle "$PRIVATE_ORACLE" --answer "$PRIVATE_ANSWER" \
  --audit "$PRIVATE_AUDIT_JSONL" --judge "$PRIVATE_JUDGE" \
  --out "$PRIVATE_REPORT"
```

`--judge` is optional for mechanical diagnostics, but every J criterion then fails. Exit zero only says the JSON report was written; inspect `all_pass`, V1–V5 and J1–J5 reasons. Mechanical and judge diagnostics each contribute 50% (`validation_score`, `judge_score`, `combined_score`); a completed all-pass requires all ten criteria and persisted `PRICED_REQUIRES_REVIEW`. Keep every attempted case in the denominator, including held/null, missing artifacts, invalid scopes and unjudged attempts. Synthetic fixtures and controls are in `tests/test_blinded_mcp_workflow_eval.py`; they are not commercial observations. Existing exact-reissue reports and rubrics remain untouched.
