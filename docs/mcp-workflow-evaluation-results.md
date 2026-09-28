# MCP quoting-workflow evaluation results

The [blinded historical-price workflow interim results](blinded-mcp-workflow-results.md) cover a separate population; their 18 attempts do not change or pool with the reissue results below.

This is a public-safe aggregate of historical-source **reissue** evaluations at code revision `6b495696c34d44bcaf5db34cb57d677f5258a40a`. Requesters authorized proposing specified historical prices; the exercise measured source retrieval and complete, pending-review draft fidelity, not blind price prediction, current costs, customer release, or business outcomes. Workers and independent judges used `codex/gpt-6-luna` at max reasoning with fast mode over real standard MCP through the existing CC transport, without a native Codex login or a Claude model. The [evaluation contract](mcp-workflow-evaluations.md) defines the frozen five mechanical (V) and five judge (J) criteria: each contributes 50% to a diagnostic score, but a completed all-pass requires all ten and a persisted `PRICED_REQUIRES_REVIEW` draft.

## Valid-fixture batches

| Batch | Attempts / persisted priced drafts | Mechanical V | Independent judge J | Completed all-pass |
|---|---:|---:|---:|---:|
| Corrected v2 diagnostic | 3 / 3 | 15/15 | 14/15 | 2/3 |
| Corrected v2 fresh | 3 / 3 | 15/15 | 15/15 | 3/3 |
| Final matched, repeating the diagnostic cases | 3 / 3 | 15/15 | 15/15 | 3/3 |
| Final new-source confirmation, original judgment | 3 / 3 | 15/15 | 14/15 | 2/3 |

The diagnostic miss was J3: an answer calculated the extension correctly but failed to distinguish the unit price displayed on the PDF from its fuller underlying precision. The final confirmation used three preselected RFQs and four source documents absent from earlier batches; selection and original-PDF checks preceded the precision-skill edit. The matched inputs, client, profile, runtime lock, and other skills remained unchanged; the estimator skill gained the reviewed precision instruction.

The original confirmation judge passed J1–J4 for all three cases and J5 for two. It failed J5 on a statement that current lead time, validity and terms would be confirmed before release, treating that process requirement as an unsupported promise. Evidence-based adjudication found a false positive: the message states no current commercial terms, delivery date, guaranteed outcome, approval or release, and the internal handoff expressly requires the same confirmation. A blinded independent paired calibration accepted the unchanged submission and rejected a version containing fabricated delivery and commercial guarantees. This resolves the distinction against the evidence, not by majority vote or a relaxed criterion.

The original final result remains **5/6 all-passes** (V 30/30, J 29/30). The separately recorded adjudicated result is **6/6** (V 30/30, J 30/30), with the confirmation batch at 3/3 after adjudication. No quote was rerun or rewritten to obtain that result, and the original answer, trace, judgment and grade remain intact. Judge disagreement is a limitation, not evidence of perfect reliability.

Across the two final batches, six successful priced drafts were persisted after seven `keller_quote` invocations: one malformed request was rejected before persistence and then corrected. The recorded standard-MCP traces contain 85 calls including discovery. Eight source lines and their eight original PDFs were rechecked against source arithmetic, requested identities, hashes, and the skill text actually read by each worker; each saw the accepted precision rule. Skills, client, and runtime-lock hashes matched the frozen version. Fixture manifests bind SHA-256 of canonical `json.dumps(obj, sort_keys=True)` content; judge bindings instead hash the exact raw oracle, answer, and audit bytes. These different binding methods must not be conflated.

## Retained invalid history and learning

| Earlier v1 cohort | Attempts | Status |
|---|---:|---|
| Baseline | 3 | Invalid fixture; one answer also omitted `customer_id`. |
| Matched | 3 | Invalid fixture; wrong `--runtime-root` caused a failure and a mixed client revision impaired comparability. |
| Clean rerun | 3 | Invalid fixture. |
| Fresh | 3 | Stopped when the role-only reviewer fixture failed the named-person requirement. |

All 12 v1 attempts remain retained as nonpassing/invalid-fixture history, not an accuracy comparison with corrected v2. Provisional 2/3 passes from the original baseline and matched batches were withdrawn. Original judge files and grades, overwritten-judgment recovery, and later raw-input attestations remain privately retained; no inconvenient result was discarded. The corrected named reviewer was a directory-verified person assigned for evaluation only, not someone granting production approval. Including v2 diagnostic and fresh (six attempts) and both final batches (six attempts), the history comprises **24 attempted workflows**, including invalid and stopped attempts. Repeated cases and invalid cohorts must not be pooled into an accuracy percentage.

Each candidate-learning batch had exactly one independent reviewer. Five learnings were accepted in total and their text was saved unchanged to the relevant skills: preserve `customer_id`; distinguish standard MCP from a native login; require conjunctive V/J acceptance; correct the runtime path before retry; and disclose PDF-displayed versus full unit precision separately from extension rounding. A supplied methodology ZIP informed evidence-first diagnosis, version checks, and independent learning acceptance; its Devin-specific tool names are not runtime dependencies.

Calibration controls caught a wrong price through V3 and J2/J3/J4, a role-only reviewer through V4/J4, and a false release through V4 and J1/J4/J5. One earlier calibration judge nevertheless accepted an unchanged, precision-defective real submission that its original judge failed; the original PDF/full-answer audit supported the failure. A new independent paired calibration, explicitly separating displayed-unit precision from extension rounding, failed that defective J3 and accepted an actually explained real submission. The disagreement remains part of the record: this does not establish perfect judge consistency. Final judges received the same clarification without changing the frozen criterion content.

The grader also rejected the customer-message adjudicator's initial binding metadata: it used `calls` instead of the required `audit` key. All three recorded hashes matched the raw inputs. A separately retained copy corrected only that key; inputs, hashes and verdicts were unchanged, and both the original files and rejected grades were preserved. The final adjudicated grade passed the unchanged strict binding check.

## Limitations and verification

These small, partly repeated, historical-price reissue batches do not establish ≥90% general accuracy or better-than-Keller decisions. The separate, freshly inspected screened historical-prediction report remains 50 cases, 47 priced, three no-analog, and 9/50 all-pass (18%); reissue success neither improves nor replaces that result, and it is not a true backtest. Shared-account restrictions on workers are instructions, not operating-system holdout isolation. The drafts still need human review and cannot be released to customers by this workflow.

The local full verification rerun passed 86 TypeScript tests, 74 Python tests (16 + 18 + 40), 26 script tests, plugin `tsc`, and frozen original CSV/JSON/evalset checks. Eleven **synthetic** order scenarios yielded seven completed, two correct holds, and two validation rejections; they do not measure price accuracy. Documentation links, public-report privacy checks and `git diff --check` also passed; postflight engine diagnostics were zero. Hosted verification and database jobs did not execute because GitHub billing/spending limits blocked them, and CodeRabbit skipped draft review. PR #15 remains draft and unmerged.
