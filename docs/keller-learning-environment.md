# Keller's learning environment

The client workflow needs a maintained evidence system, not an ever-larger similarity score. This environment adds executable knowledge review and retrieval, source-aware experiment journals, a bounded improvement backlog and a reusable operator skill. They extend the existing quote, source, order and sealed-trajectory tools; they do not replace their evidence or release gates.

## Initialize and use the environment

From the checkout, run `node scripts/bootstrap-keller.mjs`. It installs the locked estimator dependencies and declared Python packages into an isolated, ignored environment, verifies required pinned Git history, and builds the estimator. A second invocation skips installation when the inputs are unchanged. The existing Ars Umbris launcher selects that installed Python automatically unless `KELLER_PYTHON` is explicitly configured; its older runtime environment remains the compatibility fallback. It performs no database writes, model calls, client scheduling or source extraction. `.capy/setup.json` defines the same bootstrap for future cloud machines and names verification commands; it has no startup services. Repository setup takes effect on its configured Setup branch, not merely because a PR contains the file.

Run `node scripts/keller-environment.mjs verify` for the repository's actual verification suite. For the private client environment, choose an owner-private absolute directory outside the checkout and run:

```sh
node scripts/keller-environment.mjs onboard --root "$PRIVATE_CLIENT_ROOT"
```

This initializes `knowledge/`, `improvement/`, `feedback/` and `requests/` and writes a private, owner-bound knowledge binding for Ars Umbris. It refuses to replace a different client binding. It does not prove durable storage across a host restart, configure a request producer or reviewer, or approve an external delivery channel. Keep this directory on an approved client-private persistent mount before live use; a sandbox-only initialization is a local pilot.

Capture actual operator outcomes with `node scripts/keller-feedback.mjs < "$PRIVATE_FEEDBACK_INPUT"`. The input names `root` (the private feedback directory), `request_file`, optional `draft_file`, `reviewer`, `disposition`, `reason` and optional `lines` containing stable `line_id`, supported `reviewed_unit_price` and reason. Dispositions are `APPROVED_FOR_HUMAN_HANDOFF`, `CORRECTION_REQUIRED`, `HELD`, `INVALID`, `FAILED` and `TIMED_OUT`. The ledger binds exact observed request/draft bytes, verifies their identity and preserves missing drafts rather than inserting zero prices. A named operator assertion is not authenticated independent grading, current-cost proof or release permission. Feedback remains operator-only; it is never automatically indexed as knowledge or delivered to a blinded worker.

## Four distinct layers

**Evidence** stays in the existing selected corpus, original private sources and read-only tools. PDF unit prices, internal calculations, manufacturing specifications and current operator-supported costs retain their own provenance and time basis. Missing evidence becomes a concrete remediation item, not an inferred price or an assumed accuracy ceiling.

Use the executable [ground-truth assessment and decision scorer](ground-truth-assessment.md) when source meaning, manufacturing support or completion is disputed. The all-case assessment turns explicitly supplied original-byte proofs into private domain states and a bounded, case-linked remediation queue; additional narratives and operator assertions cannot promote truth. The separate full-RFQ scorer requires frozen eligibility, real artifacts, independent review execution and human handoff, and preserves holds/errors/timeouts/invalid/missing attempts. Neither changes the controller's baseline semantics, certifies an exposed diagnostic as fresh confirmation, or replaces historical ±20% regression.

**Knowledge** uses the [private knowledge lifecycle](keller-knowledge.md). Candidates carry exact workflow/customer/part/revision/material scope, source hashes and eligibility dates. One independent batch review is terminal; accepted text is still inactive until separately verified and explicitly attested. The `keller_knowledge` MCP tool exposes only bounded approved records, never maintenance actions or arbitrary caller paths. It supports one query or a JSON batch of up to 50 queries. Expired, mismatched, retired or tampered records do not become usable context. This is client domain knowledge, not the coding assistant's personal memory.

**Skills and workflow tools** carry tested procedures, while knowledge records carry supporting facts and constraints. The quote worker uses the canonical quoting skill plus exact scoped knowledge when configured; its existing `keller_quote`, `keller_polygres` and `keller_sources` tools remain the drafting/evidence boundary. The new `keller-continuous-improvement` skill is operator-only and must not be injected into blinded workers. Knowledge is data to assess, not code to execute or permission to ignore source/release rules.

**Improvement work** runs through the [measured controller](keller-improvement-controller.md). A frozen job binds the actual register, evalset, baseline, source files, dependency lock and canonical skills. It invokes the real estimator and unchanged comparison gate, saves resumable stage proofs, calculates per-case changes and variance, and produces a dependency-bound backlog. It never grades a handwritten imitation of pricing. A verified duplicate is reuse of an attested experiment, not a claim that new code ran.

## The accuracy target does not move

The working goal is **above 90%** completed, independently supported live quotes over **all attempted eligible jobs**, with every required criterion passing and a named human release gate; the existing at-least-90% acceptance contract remains the minimum, not a reason to stop short of the requested goal. Historical ±20% replay, operational completion, correct holds, synthetic order checks and live decision quality remain separate results. Holds, timeouts and invalid attempts do not vanish from the completed-quote denominator. The fixed replay sample and previously examined customer-PDF cases are development diagnostics, not untouched confirmation.

The controller deliberately cannot declare a live accuracy win from an offline report. Independent job labels, live read-only workflow traces and preselected confirmation are still required by [the acceptance contract](decision-quality.md). Record operator corrections and actual workflow outcomes privately, and promote reusable mechanisms only after their provenance, review and matched behavior survive the same checks. Failed lexical experiments do not establish that knowledge, skill or tool improvements are exhausted.

The integrated 250-case diagnostic preserved every case result from a separately executed `eb4c74e` base checkout: 228 priced, 22 held, 50 all-pass (20%), median priced-case absolute error 53.0%, and mean 91.8%. This proves the environment did not change the base estimator's results, not that pricing is accurate. Comparison against the earlier `candidate-guard` artifact still records one criterion loss and one gain despite the unchanged total pass count; that artifact's source lock differs from the base checkout. Both comparisons remain recorded. The same-base control keeps all 250 targets and criteria unchanged and is not a new confirmation population or a replacement for the accuracy goal.

## References and operating boundaries

Jeremy's supplied prompt corpus is retained unchanged with SHA-256 provenance in the project's reference library. Its topic files are excerpts and indices; the detailed knowledge, workflow-resume and one-reviewer contracts were cross-checked against the earlier supplied full skill and on-call-learning references. Keller already documented many of those safety rules. This change supplies missing machinery rather than copying vendor tool names, hidden prompts, permission bypasses or implicit promotion behavior.

The [learning schedule](keller-learning-schedule.md) is separate from the [existing draft inbox automation](local-automation.md). Keep paid analysis, data refresh, human approval, source extraction and client delivery as separately authorized actions. Local checks are the engineering gate; neither hosted CI nor automation registration proves live pricing accuracy.
