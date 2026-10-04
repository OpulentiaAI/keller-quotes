# Private Keller knowledge lifecycle

`scripts/keller-knowledge.mjs` exports `KnowledgeStore` and an operator-only JSON CLI. It retains small, cited learning candidates, one independent review, explicit operator activation, and immutable retirement history. It does not generate prices, rates, repository guidance, global memory, or customer releases.

This implements the private promotion controls in [trajectory analysis](mcp-trajectory-analysis.md), not the acceptance goals in [decision quality](decision-quality.md). Tests, an `ACCEPT` verdict, and activation do **not** establish improved accuracy, the ≥90% completed-quote goal, or business outperformance. Preserve the five canonical skills' source, costing, scope, and release rules: [estimator](../.agents/skills/keller-quote-estimator/SKILL.md), [evaluations](../.agents/skills/keller-estimator-evals/SKILL.md), [register](../.agents/skills/keller-quote-register/SKILL.md), [analysis](../.agents/skills/keller-data-analysis/SKILL.md), and [Polygres](../.agents/skills/polygres/SKILL.md).

**The store is operator-managed and is not blind-safe. Never expose it, its search results, or its copied sources in any blinded scope without a separately frozen allowance covering the actual delivered bytes.** Checks reject recognizable credentials, evaluation/oracle/target/grade/holdout markers, agent-narrative authority, and numeric price/rate prescriptions. Those lexical checks are conservative screening, not proof that arbitrary text contains no secrets, private findings, disguised targets, or invented facts. Operators must approve the original sources and independent reviewers must adjudicate actual support. Returned text is reference material, never execution instructions.

## Private filesystem boundary

The caller must supply an existing, canonical **absolute** root directory outside the checkout. The root cannot be the checkout or an ancestor of it. No default, environment fallback, discovery, scratch path, or production path is selected by the library.

- The root and store subdirectories must belong to the current Unix owner and have mode `0700`. Constructor calls pin the root's device/inode. Neither construction nor search creates files, even without `readOnly`.
- Every path component must be nonsymlinked and owned by that owner or root. No ancestor may be group/other writable; the sticky bit does not exempt a writable ancestor, even when root-owned. Dot components, noncanonical paths, control characters, and paths longer than 1,024 characters are denied.
- Evidence paths are the **operator-supplied source approvals** for this call; there is no implicit source registry or automatic collection. Each source must be outside the checkout and store, have a `0700` owner-private parent, and be an owner-owned, single-link regular file with mode `0400` or `0600`, at most 2 MiB. This is a local owner's approval assertion, not authenticated authorship.
- Sources are read without following symlinks, with bounded reads and before/after file-identity checks. `sha256` hashes the complete original bytes. `excerpt` must occur as exact UTF-8 bytes in that source; a generated paraphrase or a PDF extraction not literally present in the cited file does not pass. Cite an approved, reviewed text extraction when necessary, with its own exact hash and retained upstream document provenance.

Successful stages copy the complete cited bytes to private, content-addressed files, mode `0400`. Stage replay, review, activation, and matching search results recheck both the original source and the immutable copy. Missing, changed, inaccessible, symlinked, hardlinked, or nonprivate originals fail closed; a retained copy cannot replace an unavailable original. Keep approved source snapshots available and unchanged.

## Exported API

All methods are synchronous and return plain JSON data. Errors have a stable uppercase `error.code`; callers must not treat an exception as an empty successful lookup.

```js
import { KnowledgeStore } from './scripts/keller-knowledge.mjs'

const operatorStore = new KnowledgeStore(privateRoot)
const reader = new KnowledgeStore(privateRoot, { readOnly: true })
```

The only constructor option is optional Boolean `readOnly`. It prohibits all four mutation methods. Read-only construction/search performs no initialization, lock creation, or store writes. An existing empty private root yields `{records:[]}`. A missing root is an error.

### `stage(packet)`

The packet has exactly these keys:

```text
{
  packet_id: nonempty string,
  generator_id: nonempty string,
  candidates: [{
    index: unique nonnegative safe integer,
    kind: "procedure" | "specification",
    topic: nonempty exact string, at most 80 characters,
    statement: nonempty string, at most 300 characters,
    scope: {
      workflow: nonempty exact string,
      customer_id?: nonempty exact string,
      part_no?: nonempty exact string,
      revision?: nonempty exact string,
      material?: nonempty exact string
    },
    evidence: [{
      path: operator-approved absolute private source path,
      sha256: lowercase 64-character SHA-256,
      excerpt: nonempty string, at most 1024 characters,
      authority: "human" | "document" | "tool_observation"
    }],
    valid_from: "YYYY-MM-DD",
    valid_until?: "YYYY-MM-DD"
  }]
}
```

There may be **zero to ten** candidates, each with one to five distinct source paths. Zero candidates is a valid outcome: stop after staging; no reviewer or activation is required. `topic` names the concrete rule being reviewed, such as `drawing-revision`, `finish-check`, or `material`; it is the conflict/supersession key, not a free-text retrieval query. A procedure always needs a workflow. A business specification additionally requires `customer_id`, `part_no`, and `revision`; an unscoped specification cannot be staged. Dates must be real calendar dates, with `valid_until >= valid_from` when supplied. Strings other than excerpts must have no control characters or leading/trailing whitespace. IDs, names, and each scope value are limited to 120 characters; reasons are limited to 512. Unknown keys are rejected at every schema boundary.

The result is `{packet_id,packet_sha256,status:"STAGED",candidate_count,idempotent}`. `packet_sha256` hashes compact canonical UTF-8 JSON: object keys sorted recursively, array order retained. It is **not** the hash of arbitrary whitespace/key order in CLI stdin. Repeating the same packet ID and canonical content is an evidence-revalidated no-op. Different content under that ID fails with `PACKET_ID_CONFLICT`. Rejected or accepted candidates cannot be edited in place.

### `review(packetId, verdicts)`

Despite the parameter name, `verdicts` is the **complete review object**, not a bare array:

```text
{
  packet_sha256: the stage result's exact hash,
  reviewer_id: nonempty independent reviewer ID,
  verdicts: [{index, verdict: "ACCEPT" | "REJECT", reason}]
}
```

Give the complete unchanged batch to exactly one independent reviewer. IDs equal to the generator after case-folding cannot review it. Identity strings are owner assertions, not software-authenticated people or proof of independent model execution. The external operator remains responsible for genuinely independent review without source transcripts, write access, requested outcomes, or retries.

The first received review attempt is terminal. Missing, duplicate, conflicting, malformed, unknown-key, lowercase, or unsafe **indexed verdicts** reject the affected candidates. A bad review envelope, wrong packet hash, self-review, unassignable/unknown index, unavailable result, or evidence failure rejects the complete batch. Pass `null` when the reviewer fails or times out; do not repair its response or query another reviewer. Malformed raw reviewer output may also be supplied as a string so the failure is recorded. Every later attempt fails with `REVIEW_ALREADY_RECORDED`, including after a wholly rejected review. Do not evade this gate by restaging the same rejected batch under another ID.

The result includes `{packet_id,packet_sha256,submission_sha256,reviewer_id,failed,verdicts,review_sha256,status}`. `status` is `REVIEWED` or `REVIEW_FAILED`; every candidate has exactly one normalized verdict. The immutable review records a digest of serializable submitted input, not unsafe raw text. `submission_sha256` is `null` when the submission cannot be serialized. All-rejected and zero-candidate reviews are valid. **Acceptance alone never creates an active record.**

### `activate(packetId, candidateIndex, operatorAttestation)`

Activation requires an unchanged accepted candidate, an independent recorded review, independently reverified original/copied evidence, and exactly:

```text
{
  operator: explicit nonempty named operator,
  reason: explicit nonempty reason,
  development_report_sha256: lowercase 64-character SHA-256,
  confirmation_report_sha256: lowercase 64-character SHA-256
}
```

Both report hashes are retained exactly. This is a **local operator attestation**, not software-authenticated human identity, independently opened/graded report evidence, or proof of achieved accuracy. Report files are not read by this library; operators retain and independently verify them through the separate development/confirmation workflow. No global-memory or repository write follows activation.

Successful activation returns `{packet_id,packet_sha256,review_sha256,candidate_index,operator_attestation,status:"ACTIVE",record_id,record_sha256}`. The immutable activation event's content hash is both `record_id` and `record_sha256`; it binds the packet, review, selected candidate, attestation, and preceding history.

An identical statement at an identical active scope, with the same validity window and evidence, records a terminal duplicate disposition and returns `status:"DUPLICATE_REJECTED"`, `disposition:"KEEP_EXISTING_REJECT_REDUNDANT"`, the existing record ID/hash, and `disposition_sha256`. It does not activate another record, even under another topic. **Different topics can coexist** at the same scope, so complementary procedures or part specifications do not overwrite one another. Changed text, validity or grounding with the same **kind + topic + exact scope** is a conflict: `ACTIVE_SCOPE_CONFLICT`. The operator must explicitly retire the old record with a reason before activating that topic's replacement; a renewed source or eligibility window is not discarded as a redundant update. There is no semantic conflict oracle or last-write-wins; operators must also review cross-topic contradictions. An activated or duplicate-disposed candidate cannot be activated again (`CANDIDATE_ALREADY_DISPOSED`).

### `search(query)`

The exact query shape is flat, with **`as_of`**, not `date` or `scope`:

```js
reader.search({
  workflow: 'quoting',
  as_of: '2026-10-04',
  customer_id: 'SYNTHETIC-CUSTOMER',
  part_no: 'SYNTHETIC-PART',
  revision: 'A',
  material: 'steel',
  limit: 10,
})
```

`workflow` and `as_of` are required; the four context fields and `limit` are optional. `limit` is an integer from 1 to 10, default 10. Only `ACTIVE` records backed by accepted independent reviews are eligible, with inclusive `valid_from <= as_of <= valid_until` (no upper bound when omitted). Every **declared record scope field** must equal its query field exactly. No case folding, normalization, fuzzy retrieval, inferred material/revision, or wildcard customer match is applied. Missing business context means no specification match. Extra query context can still match a workflow-only procedure; it cannot bypass any declared restriction.

The result is:

```text
{
  records: [{
    record_id, record_sha256, packet_id, packet_sha256, review_sha256,
    candidate_index, kind, topic, statement, scope,
    evidence: [{path, sha256, excerpt, authority, copied_path}],
    valid_from, valid_until?, status: "ACTIVE", operator_attestation
  }],
  as_of, limit, usage: "reference_only", blind_safety: "NOT_ATTESTED"
}
```

Matching records are ranked **before** applying the limit: more declared exact scope fields first, then newer `valid_from`, then ascending record ID. This prevents workflow-wide procedures from crowding out exact customer/part/revision specifications; it is deterministic retrieval, not a pricing weight or evidence of manufacturing equivalence. Missing revision still excludes a specification. Every read revalidates journal content hashes and all returned evidence's original/copy hashes and excerpt. Evidence failure is an error, never silently omitted as if retrieval succeeded. Source paths, excerpts, scope identifiers, and attestation names remain private; do not forward this result to customers or interpret `NOT_ATTESTED` as permission for blinded retrieval.

### `retire(recordId, reason)`

An explicit nonempty reason appends a retirement event binding the active record hash. It returns `{record_id,record_sha256,status:"RETIRED",reason,retirement_sha256}`. Retired records no longer match search, but their packet, review, activation, evidence, and retirement remain unchanged. Unknown IDs fail with `RECORD_NOT_FOUND`; repeated retirement fails with `RECORD_ALREADY_RETIRED`. Retirement is still possible when an original source is unavailable, provided the journal itself is intact.

## JSON CLI

Use an explicit owner-selected root and private stdin/output files; these environment names are caller placeholders, not library defaults:

```sh
node scripts/keller-knowledge.mjs stage --root "$PRIVATE_KNOWLEDGE_ROOT" < "$PRIVATE_PACKET_JSON"
node scripts/keller-knowledge.mjs review --root "$PRIVATE_KNOWLEDGE_ROOT" < "$PRIVATE_REVIEW_REQUEST_JSON"
node scripts/keller-knowledge.mjs activate --root "$PRIVATE_KNOWLEDGE_ROOT" < "$PRIVATE_ACTIVATION_REQUEST_JSON"
node scripts/keller-knowledge.mjs search --root "$PRIVATE_KNOWLEDGE_ROOT" < "$PRIVATE_QUERY_JSON"
node scripts/keller-knowledge.mjs retire --root "$PRIVATE_KNOWLEDGE_ROOT" < "$PRIVATE_RETIREMENT_REQUEST_JSON"
```

The action precedes exactly `--root DIR`; extra arguments are errors. Stdin is one UTF-8 JSON value. Stage and search consume their API objects directly. The other actions require these exact envelopes:

| Action | Stdin object |
| --- | --- |
| `review` | `{packet_id, review: <complete review object or null on failure>}` |
| `activate` | `{packet_id, candidate_index, operator_attestation}` |
| `retire` | `{record_id, reason}` |

Success writes one `{ok:true,result:<API result>}` JSON line to stdout and exits 0. A consumed failed review also exits 0 but explicitly returns `REVIEW_FAILED` and all `REJECT` verdicts; that is not approval. Errors exit 1 with `{ok:false,error:{code}}`, without raw source contents, paths, or native stack traces. Invalid transport JSON cannot identify a valid review attempt; report reviewer failure through the valid `review` envelope with `null`, rather than retrying or fixing the judge.

Stdin and complete stdout are bounded to 256 KiB. JSON nesting is limited to 12 levels, arrays to 1,000 elements, and objects to 32 keys before stricter action schemas apply. Duplicate JSON object keys, invalid UTF-8, non-JSON API values, oversized inputs/results, and unknown schema keys are rejected. Output is not silently truncated. Search uses the read-only constructor option.

## Immutable history and locking

`evidence/<sha256>.bin` contains copied bytes. `events/<ordinal>-<sha256>.json` contains the immutable stage/review/activation/duplicate/retirement journal. Each event binds the previous event hash; all events are hash/schema/sequence checked on every operation. Mutations acquire an atomic, exclusive `.writer.lock`, commit through private temporary files and no-overwrite links, and fsync files/directories. Search never acquires a writer lock; if one is observed before or after its read, it fails with `STORE_BUSY`. Concurrent writers fail busy rather than overwrite or shop reviews.

There is no automatic stale-lock theft, repair, pruning, or rotation. A crash may leave a lock or incomplete write requiring an operator to establish quiescence and inspect the immutable files before recovery. The journal is limited to 4,096 events; `STORE_FULL` requires a separately managed new private store/retention decision. These protections detect content mutation, unsafe permissions, broken chains, and missing interior events; they are **not** a tamperproof ledger against the owner, who can change modes, rewrite/re-hash history, or truncate its tail. Keep independently frozen hashes/allowances outside this store when that stronger boundary is needed.

Synthetic fixtures live under the current owner's home directory in `.capy/work`, not under a writable temporary ancestor. Run the actual lifecycle, CLI, filesystem, evidence, scope/date, and multiprocess mutation tests with:

```sh
node --test scripts/test/keller-knowledge.test.mjs
```
