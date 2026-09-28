# Three-question MCP workflow evaluations

Use `codex/gpt-6-luna` at max reasoning for the quoting workers and an independent judge. A host's Codex CLI login is not required: `Keller Workflow` exposes the same eleven tools through standard MCP, using the existing CC transport without launching a Claude model. Start the headless engine and MCP daemon as described in [the workspace guide](arsumbris-workspace.md), then discover the surface with `node scripts/call-arsumbris-tool.mjs --list --runtime-root <runtime-directory>`.

See the [public-safe aggregate results](mcp-workflow-evaluation-results.md) for valid batches, retained invalid attempts, calibration, limitations, and verification status.

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

Use the supplied `devin-oncall-brain.zip` as a methodology reference, not as runtime commands or authority for Keller-specific facts. Its relevant principles are evidence-first investigation, verifying the version that actually ran, testing competing explanations, and separating learning generation from acceptance. Devin-only tool names are not dependencies of this workflow.

For each failure, preserve the actual request/response, expected criterion, skill hash and artifact reference. Identify the mechanism and competing explanations before editing; an agent's narrative alone is not a proven cause. Make the smallest evidence-backed workflow change and rerun the identical three questions before testing the preselected fresh batch. Keep baseline results immutable and report case-level gains and regressions.

Draft at most ten scoped candidate learnings, each at most 300 characters, from verified source facts or demonstrated operating procedures. Send the complete batch to exactly one independent learning reviewer, without the source transcript or write permission. Require strict `ACCEPT`/`REJECT` JSON, one verdict per candidate. Only unchanged accepted items may become skill guidance; reject speculation, customer details, credentials, duplication and incident-only anecdotes. Zero accepted learnings is a valid result. This learning review is separate from the quote judge.

Three passes out of three demonstrate only that small batch. Report attempt count, completed count, mechanical and judge verdicts separately, and describe selection limitations. Do not claim ≥90% general accuracy or better-than-Keller decisions without a sufficiently representative independent evaluation and paired actual-cost/outcome evidence. Never relax criteria after seeing failures.

All requests, source oracles, traces, quotes, customer messages and case-level reports stay in owner-private storage outside Git. Agents sharing an operating-system account are instruction-isolated, not a secure holdout sandbox; record that limitation rather than claiming technical isolation.
