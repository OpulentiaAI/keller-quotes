# Three-question MCP workflow evaluations

Use `codex/gpt-6-luna` at max reasoning for the quoting workers and an independent judge. A host's Codex CLI login is not required: `Keller Workflow` exposes the same eleven tools through standard MCP, using the existing CC transport without launching a Claude model. Start the headless engine and MCP daemon as described in [the workspace guide](arsumbris-workspace.md), then discover the surface with `node scripts/call-arsumbris-tool.mjs --list --runtime-root <runtime-directory>`.

See the [public-safe aggregate results](mcp-workflow-evaluation-results.md) for valid batches, retained invalid attempts, calibration, limitations, and verification status.

## Opt-in blinded evidence scope

Schema-1 scopes freeze only price rows and part/quantity request identities. The scoped register now reconstructs only those frozen fields, using the frozen document locator as its `quote_letter` source label rather than copying a live historical letter. Unfrozen engineering metadata cannot influence retrieval. Additional line selectors and `cost_basis` are denied before execution; rich `evidence`/`evidence_candidates` packets are omitted from scoped artifacts/results but retained in ordinary operator drafts. Use a separately versioned, independently frozen scope to evaluate richer engineering evidence, and do not compare earlier broad-metadata scoped runs as a matched code-only study.

For genuinely blinded historical cases, prepare an owner-private (`0700` directory, `0600` regular file), absolute scope JSON outside Git and run every MCP call, including discovery, through `node scripts/call-arsumbris-tool.mjs --list|--call --evaluation-scope "$PRIVATE_SCOPE" --audit "$PRIVATE_TRACE"`. Reuse the exact scope bytes throughout one attempt. The caller binds each worker-visible response and audit event, including failures, to their SHA-256; preserve the scope hash with the frozen case manifest. A malformed or changed scope fails closed. This is an opt-in guarded **client view of the actual standard MCP backend**, not a separate mock backend or a change to the normal unscoped profile.

Schema version 1 has exactly these fields (dates are valid `YYYY-MM-DD`; `date_stamp` may be `""`):

```text
{schema_version:1, case_id, corpus, quote_date, excluded_quote_nos:[string],
 request:{order_id, quote_date, customer, customer_id, reviewer,
          parts:[{line_id, part_no, quantity}], charges:{shipping,tax}},
 eligible_prices:[{quote_no,item_no,quantity,unit_price,extended_price,
                   quote_date,letter_date,date_stamp,part_no,customer_id,
                   source_price_field,price_basis,status,source_path,
                   pdf_sha256,transcript_sha256}],
 allowed_files:[absolute canonical public skill/contract/synthetic-example paths]}
```

Build `eligible_prices` from the independently verified, hash-frozen register, never from the target's heldout prices. Exclude the **entire** target quote and every row with an invalid or nonprior quote, letter, or last-touch date; exclude an entire document if its page text also contains heldout or future prices. Keep source paths, document/transcript hashes, every quantity break, and full price precision; an empty `item_no` is valid. Only `customer_quote_pdf` rows with unknown outcome and strictly earlier dates qualify. Freeze the request identity, named reviewer, exact requested lines and supplied shipping/tax in the scope. Do not put a private oracle or heldout price in the scope. The guard matches complete verified price/provenance identities with exact decimal-equivalent amounts; it never treats search snippets or page text as verified numeric price authority. Besides canonical skills and public type definitions, the allowlist accepts only the public contracts `docs/pricing-evals-and-orders.md`, `estimator/src/order.ts`, and `estimator/src/types.ts`, plus explicitly synthetic examples.

Scoped discovery exposes only `read_file_pinned`, `au_diagnostics`, `au_type`, `keller_polygres`, and `keller_quote`. Pinned reads accept only listed canonical public files; graph navigation and raw source readers are refused. Polygres is confined to the selected corpus, filters prices and search hits to eligible evidence, retains backend pagination offsets even when a filtered page is empty, and refuses excluded documents before page calls. Quote inputs and returned request/review must match the scope; any ineligible returned analog rejects the entire draft, including otherwise blocked drafts. Successful and blocked valid draft payloads are unchanged for persisted-artifact comparison. Malformed/error responses and alternate MCP content channels cannot enter the guarded audit. Keep all scope, trace, and response files private. This is application-level filtering on a shared OS account, **not an OS sandbox**: a worker with direct shell or database access can bypass the client. The grader must additionally require scope-bound traces and independently inspect price evidence before crediting a blinded result.

## Freeze before running

Each run contains exactly three RFQs, with one fresh worker context per question. Freeze the request content, private independent source oracle, selected corpus/register hash, criterion version, model/effort, runtime lock, and actual skill content hashes before observing outputs. Record the checkout SHA too: a working-tree skill hash, rather than HEAD alone, identifies what the worker actually read. Retain a separate fresh three-question batch before making changes. Workers may read their requests and the rubric, but never the oracle, prior results, another worker's output, or the database outside MCP.

Preflight the oracle as carefully as the worker: verify original source hashes and decimal extensions, ensure every required input is supplied, and identify a **named person** for pending human review. A role such as “authorized estimator” is not a person's name. The oracle's `reviewer_identity` must contain `name`, `kind: "human"`, and a documented `source`; the request and returned reviewer fields must equal that name. A synthetic evaluation assignment grants no production approval. If an input defect is discovered after a run, retain the invalid run and issue a new fixture version with an explicit change log; do not quietly patch the oracle or interpret the gate more generously.

Name the population precisely. Historical-price reissue requests measure retrieval and complete-draft fidelity when the requester explicitly authorizes proposing specified historical prices. They do not measure unseen-part price prediction, current manufacturing costs, or business outperformance. Keep their results separate from cutoff-aware historical prediction and from synthetic arithmetic tests. Do not relabel one as another to improve a headline score.

## Equal validation and judging

Mechanical validation and independent judgment each contribute half of a diagnostic score, with five equally weighted binary criteria per half. A completed all-pass requires **all ten**, plus a persisted `PRICED_REQUIRES_REVIEW` draft. A partial score cannot compensate for an incorrect price, missing artifact, source substitution, or release claim. Holds, tool failures, malformed answers and absent judge verdicts stay in the three-attempt denominator; a correct hold can pass safety checks but is not a completed quote.

| Mechanical criterion | Required evidence |
|---|---|
| V1: execution and artifacts | A real standard-MCP trace includes canonical skill reads, evidence reads and draft generation; returned JSON/Markdown/review match the persisted draft and tool response. |
| V2: request fidelity | Order/customer/date, every line's part and quantity, and explicit shipping/tax match the frozen request. |
| V3: price and arithmetic | Finite positive prices satisfy the unchanged ±20% source-price guard. For an **exact reissue**, each extension must additionally match the independently reconciled printed extension within one cent; subtotal/total reconcile without silently dropping source precision. |
| V4: completion and review | Complete finite draft, pending named reviewer, human review required, and release authorization false. |
| V5: source fidelity | Every line's quote/part/quantity/source path/PDF hash/full unit precision matches the independent oracle and observed tool evidence; the source event precedes the request date. |

| Independent judge criterion | Required judgment |
|---|---|
| J1: intake | Correct customer/part/revision/quantity/UOM and authorized scope, with no unsupported equivalence or invented approval. |
| J2: evidence | Pricing choices follow probative issued-price evidence rather than search snippets, internal calculations, supplier amounts or assumed outcomes. |
| J3: decisions | Source precision and rounding are handled correctly; incompatible curves are not mixed and current cost/lead-time facts are not invented. |
| J4: reviewer handoff | Scope, basis, explicit charges, pending review, unresolved terms and required confirmations are actionable and accurate. |
| J5: customer-safe draft | A separate pending-review message includes requested lines and charges without exposing internal costs, other-customer identities, private paths/hashes or unsupported promises. |

The judge receives frozen requests/oracles, final artifacts and complete MCP traces, not the worker's reasoning, prior scores or desired verdict. Require one strict `pass`/`fail` verdict per J criterion with concrete artifact/trace citations. The judgment also carries `input_sha256: {oracle, answer, audit}`, each the lowercase SHA-256 of the exact raw input file bytes. The grader rejects missing or mismatched bindings, even when the case ID matches, so a judgment from a different attempt cannot silently apply. Give each judge explicit output paths and preserve original judgments before adding provenance metadata or adjudication. Missing, duplicate or malformed verdicts fail closed. Calibrate the judge and validator against independently prepared wrong-price, false-release and role-only-reviewer artifacts; these controls are not completed quoting cases and must not inflate the quote denominator. Review disagreements against the original evidence, never resolve them by majority vote or by asking a judge to be more generous.

Run the independent local grader after the agent has finished, using owner-private input/output paths outside Git:

```sh
python3 scripts/grade-mcp-workflow.py \
  --oracle "$PRIVATE_CASE_ORACLE" --answer "$PRIVATE_AGENT_ANSWER" \
  --audit "$PRIVATE_MCP_TRACE" --judge "$PRIVATE_JUDGMENT" \
  --out "$NEW_PRIVATE_GRADE"
```

The oracle holds `case_id`, the frozen `request` (including `requested_lines`, corpus, reviewer and explicit charges), `reviewer_identity`, the corresponding verified CSV `lines`, and `expected_total_exact_source`. The answer holds `case_id`, an unchanged `draft` tool payload, per-line `evidence`, `reviewer_handoff`, `customer_message` and `unresolved`. The judge returns `case_id`, `input_sha256` and exactly five `criteria` entries with `id`, `verdict`, `reason` and evidence citations. The grader independently opens the UUID-referenced persisted draft and compares it with the trace and submitted answer. Valid graph `null` or array results are not malformed business payloads; Keller evidence/draft payloads still require objects. Omitting `--judge` yields mechanical results with all judge criteria unpassed, not an all-pass. The command writes a diagnostic result; inspect `all_pass` rather than treating process exit zero as a passed quote. The output's parent directory must be owner-private (`0700`). Synthetic schema examples and rejection coverage live in `tests/test_arsumbris_workflow_eval.py`; they do not contain customer records.

## Diagnose, learn, and rerun

Follow the mandatory [private trajectory analysis and learning procedure](mcp-trajectory-analysis.md) for every iteration. It freezes execution identity and available session coverage, reconstructs only observed actions, compares all ten criteria case by case, investigates every pass-to-fail loss even when the aggregate improves, and gates any guidance change through independent learning review. This is separate from the quote judge and cannot alter the original rubric or verdicts. The supplied analyzing-sessions and oncall material is methodology, not Keller-specific evidence, runtime authority or a Devin dependency.

For each failure, preserve the actual request/response, expected criterion, skill hash and artifact reference. Identify competing explanations before editing; an agent's narrative alone is not a proven cause. Make the smallest evidence-backed workflow change and rerun the identical three questions for debugging before testing the preselected fresh batch. Keep baseline and invalid results immutable and report case-level gains and every criterion regression.

Three passes out of three demonstrate only that small batch. Report attempt count, completed count, mechanical and judge verdicts separately, and describe selection limitations. Do not claim ≥90% general accuracy or better-than-Keller decisions without a sufficiently representative independent evaluation and paired actual-cost/outcome evidence. Never relax criteria after seeing failures.

All requests, source oracles, traces, quotes, customer messages and case-level reports stay in owner-private storage outside Git. Agents sharing an operating-system account are instruction-isolated, not a secure holdout sandbox; record that limitation rather than claiming technical isolation.
