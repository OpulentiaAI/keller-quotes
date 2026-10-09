# Keller Ars Umbris workspace

This repository is the `keller-quotes` entry repo for the pinned Ars Umbris `0.0.2-alpha` runtime. `.arsumbris/repo.yaml` declares the type peers used by the layout, skill/profile instances, and MCP tools; `.arsumbris/workspace.yaml` edits this repository and discovers the `host-bundle` and `mcp-bundle` closures. The host opens `workspace-layout.yaml` into a branded evidence reader, source tree, and `Keller Codex` session launcher, with [[start here]] as the opening overview. The public [[source-catalog]] and [[organization-catalog]] are typed indexes, not replicated private records.

Follow native wikilinks with **Ctrl-click** on Linux or **Cmd-click** on macOS. If Ars asks where to open the file, choose the document **Tabs** destination. An ordinary click selects the editor text; it does not follow the reference.

## Install, build, and open

Use an authorized Linux desktop account with Git access to the locked Ars Umbris repositories, Node 24, npm, pnpm honoring the host's `packageManager: pnpm@11.1.1`, Rust/Cargo, native compiler tools, and Python with `venv` and pip available. The GUI also needs a working desktop display and Electron's system libraries. Setup does not install these system prerequisites or change their versions. It refuses a mismatched existing checkout instead of resetting it; move or repair that checkout explicitly before retrying.

For the optional native `Keller Codex` host session, install Codex CLI separately and pass `--codex-binary /absolute/path/to/codex` to setup if it is not already registered in Ars. This session verified CLI `0.154.0` at `~/.capy/work/keller-au-bootstrap/codex-cli/node_modules/.bin/codex`. The option registers that executable, not authentication; an existing binary entry is preserved. An approved Codex account must sign in through the host's session terminal before testing that native session. External agents using the stdio MCP workflow do not need a Codex CLI login.

From the repository root, the default runtime location is `~/arsumbris`. Use a fresh runtime directory when upgrading an older pinned installation; setup never resets an existing checkout. Pass the same override to setup and every launch command:

```sh
node scripts/setup-arsumbris.mjs --runtime-root "$HOME/arsumbris-0.0.2-alpha"
node scripts/start-arsumbris.mjs host --runtime-root "$HOME/arsumbris-0.0.2-alpha"
```

Setup verifies the coherent `0.0.2-alpha` lock, builds the runtime and Keller host overlay, prepares the managed Python/estimator dependencies, registers the workspace, and writes the ignored MCP-client config. It does **not** fabricate private source bindings or authenticate Codex. Do not substitute upstream `main`. For a normal GUI launch, start **host alone**: the Keller launcher prepares the native graph for `AU_ENTRY` (the absolute `keller-quotes` folder, not the layout YAML) before opening Electron. The 39,975-document cold graph can exceed the upstream renderer's 15-second serving deadline, so this launch path waits for full readiness for up to 120 seconds instead of opening a prematurely failed gate. It reuses an existing engine without taking ownership, never launches a second engine over a live PID, and stops only its own engine on cancellation, failure or host exit. If running headless MCP instead of the GUI, start `engine` and then `mcp` as separate long-lived commands with the same `--runtime-root`, and use `.keller-local/arsumbris/mcp.json` with the approved stdio client. The host's `--software-rendering` option is available when GPU rendering is unavailable. These commands do not start a customer workflow or hosted model call.

The host's default session profile is [[Keller Codex]]. It selects the pinned Codex adapter, five typed `mcp.skill` wrappers, the minimal standing safety inject, graph read tools, `mcp.tool.keller_polygres`, bounded read-only `mcp.tool.keller_sources`, and the root-owned `mcp.tool.keller_quote` for internal requires-review order drafts from explicit operator costs or read-only corpus evidence. `[[Keller Workflow]]` selects the same eleven tools, five skill wrappers, and standing inject over the CC stdio MCP transport so an external agent (including Luna-max) can run its own model and call real MCP tools without a native Codex login or launching Claude. `[[Keller Graph Readonly]]` selects only graph reads; `[[Keller Polygres Readonly]]` selects only the bounded database read tool. Those two narrow profiles use the CC adapter for the generic stdio MCP bridge (`node scripts/start-arsumbris-mcp-client.mjs --profile 'Keller Graph Readonly'` or `--profile 'Keller Polygres Readonly'` after starting engine and MCP), and supply no skills or standing injects. All four use `nativeToolAllowlist: []` to prevent a native shell from bypassing their gates; none grants credentials. Each quoting wrapper points to its **canonical** `.agents/skills/<name>/SKILL.md` and asks the agent to read it through `read_file_pinned` before acting. If the source skill or MCP service cannot be read, stop or hand off to an operator. The wrapper body is not a substitute for the canonical procedure.

For a headless external-agent evaluation, an authorized operator starts `node scripts/start-arsumbris.mjs engine --runtime-root "$HOME/arsumbris-0.0.2-alpha"` and `node scripts/start-arsumbris.mjs mcp --runtime-root "$HOME/arsumbris-0.0.2-alpha"` as separate long-lived processes. The agent can use any standard stdio MCP client against `node scripts/start-arsumbris-mcp-client.mjs --profile 'Keller Workflow' --runtime-root "$HOME/arsumbris-0.0.2-alpha"`, or use this small one-shot protocol caller (Node 24, same pinned runtime) to discover full tool schemas and invoke one tool per process:

```sh
node scripts/call-arsumbris-tool.mjs --list --runtime-root "$HOME/arsumbris-0.0.2-alpha"
printf '%s\n' '{"name":"au_diagnostics","arguments":{"limit":1}}' | node scripts/call-arsumbris-tool.mjs --call --runtime-root "$HOME/arsumbris-0.0.2-alpha" --timeout-ms 1200000
```

Send the JSON request via stdin, **not argv**; the caller writes structured JSON to stdout. `--timeout-ms` defaults to ten minutes and can be raised for long quote calls. For a private per-session request/result trace, make an owner-owned `0700` directory outside the tracked repo and add `--audit /absolute/private/session/calls.jsonl` to both invocations; the caller creates an owner-only `0600` file or appends to an existing safe file, rejecting symlinks, shared directory permissions, and unsafe file ownership/modes. Its trace captures timestamps, tool names, full inputs, and full results, so treat both trace and stdout as private customer/cost evidence. The generated `.keller-local/arsumbris/mcp.json` still exposes only the two narrow read-only connections; the full workflow requires explicit `Keller Workflow` profile selection. No DSN belongs in a command line, graph, log, or public artifact. Discovery and evidence reads must go through the actual MCP protocol rather than direct plugin calls. This profile and these application-level allowlists are **not an OS sandbox**.

To inspect the graph, ask `au_instances_of` for `mcp.skill::au-mcp-sdk`, `agent-profile::au-mcp-sdk`, `keller.source::keller-quotes`, and `keller.organization::keller-quotes`; use `au_members`/`au_type` for discovery, resolve the selected instance, and inspect `au_diagnostics`. The profile includes `au_files`, `au_follow`, and `read_file_pinned` for source navigation. A dependency listed in `repo.yaml` gives permission to reference its types; the workspace's `discover` list mounts the UI/MCP bundles. These files and any device registry entries are separate concerns.

The caller refuses credential-named inputs and PostgreSQL credential strings before opening an audit file, including credentials nested in the quote request's JSON string; valid private business evidence is not rewritten. Startup failures report fixed, safe categories such as `[runtime]` or `[audit]`, and failures after a safe audit is open are recorded without exposing runtime paths or exception values. For `[runtime]`, compare `--runtime-root` with the operator's installed path rather than inferring an authentication problem. Use the [three-question workflow evaluation contract](mcp-workflow-evaluations.md) to validate both the agent artifacts and the independent judge.

## Private evidence binding

The [[map - Keller operator findings]] is the operator-only knowledge entry point for the retained source and evaluation findings.
The repository declares the already pinned `au-base-types` and `au-weave` vocabularies and uses native `claim`, `source`, `map.overview` and `weave-premise` records, with typed `based_on` and `about` relations.
The [[premise - Keller operator findings]] excludes hidden case targets, customer-specific solutions, credentials and unsupported business claims from this graph.
Documenting a finding does not activate the private knowledge store, change a profile, widen the frozen worker-file allowlist, promote a pending code branch or authorize a customer release.
These records expose dated aggregate observations to authorized operators; a type claim, citation or hash does not authenticate its issuer or reviewer.
The [[git-evidence-access]] guide connects those records and pending code checkpoints to an authenticated private archive with Git-pinned checksums. Recovery happens outside the checkout and does not bind private source roots or widen worker access automatically.

The GUI can start its configured MCP daemon while opening the workspace or selecting **New session**; opening the layout does not start a model exchange. After that, or after starting both headless services, run `node scripts/verify-arsumbris-mcp.mjs --runtime-root <runtime-directory>` to check the two scoped standard MCP connections and perform a live read-only corpus lookup. `--skip-corpora` skips that database read; it is not database-access verification. The smoke check fails on unresolved graph errors. The generic stdio bridge uses the upstream CC transport without launching Claude or changing the Codex model selection.

The pinned upstream runtime is an early alpha, not a security sandbox. Tool allowlists and bounded readers narrow the application surface but do not isolate plugin code from the operating-system account. Run it only under the authorized private account. This setup was verified on Linux; the DBF reader uses Linux file-descriptor paths and must not be claimed portable to macOS without a separate test.

No private PDF, DBF, transcript, customer register, connection string, or customer-specific quote artifact is packaged by this repo. An authorized owner binds existing private roots in ignored `.keller-local/arsumbris/sources.json`; setup preserves rather than invents this file. Its **only permitted keys** are `fabritrak`, `pdfs`, `transcripts`, and `manufacturing-audit`, each an absolute path to an approved existing directory. For example, substitute real owner-approved paths and keep the file owner-private:

```json
{
  "fabritrak": "/absolute/private/fabritrak-root",
  "pdfs": "/absolute/private/pdf-root",
  "transcripts": "/absolute/private/transcript-root",
  "manufacturing-audit": "/absolute/private/audit-root"
}
```

```sh
chmod 600 .keller-local/arsumbris/sources.json
```

The `fabritrak` binding must contain both the primary source snapshot and supplemental FORMULA/BOM files when those are approved for inspection; binding only the primary DBFs hides the manufacturing supplement. `KELLER_PDF_CORPUS_DIR`, `KELLER_DBF_SNAPSHOT_DIR`, `KELLER_DOCUMENT_EVIDENCE_DIR`, and `KELLER_SOURCE_AUDIT_DIR` in the catalog name locator roles, not necessarily exported environment variables. Verify paths, manifest hashes, and access rights on each host before using raw files. `mcp.tool.keller_sources` provides closed-set bounded read-only `sets`, `list`, `read`, `dbf_schema`, exact-key `dbf_rows`, and definition-only `dbf_catalog`; it cannot mutate a source, and reading historical material/routing records does not prove present costs or times. The PDF archive, transcript summary and records, verified derivative, and DBF audit have different failure accounting; missing or failed records must stay visible rather than disappearing from a denominator. A graph catalog entry is a pointer, not a claim that binaries are mounted or that a PDF viewer can open them directly.

For the read-only database tool, bind the existing `POLYGRES_DIRECT_URL` privately, enforce the documented TLS/database identity guard, and explicitly select corpus `5089cd30b1b51f3903c6f16459dcf883a36137156086fc105220f594faf64a90` in database `app_peb68ccd10bc4e4ea3b43852`. `corpora` discovers public IDs; `search` finds page citations, `page` reads a cited page, and `prices` returns verified customer-PDF prices by exact part or quote. Search text is not a price. The tool accepts no SQL or write operation and bounds output. Consult `.agents/skills/polygres/SKILL.md` and `docs/polygres-document-evidence.md` for historical basis and access constraints. The direct URL is secret and must never appear in the graph, logs, reports, Git, or a customer artifact. The pooled URL is not a libpq substitute.

## Quoting and release boundary

For DBF quote lines, `dbf_rows` takes an exact `quote_no`. For material, operation, and formula catalogs with a known ID, pass an exact `record_id` instead; the reader uses only the table's single `ID`, `OPER_ID`, or `FORM_ID` column. If the ID is unknown, use bounded `dbf_catalog` discovery below. Both exact filters together are rejected. Each call remains bounded to 20,000 scanned records and at most five returned rows, with continuation; memo fields remain unresolved unless explicitly requested through the memo options below.

The committed `quotes.csv` and `quotes.json.gz` are frozen internal-calculation breaks, not necessarily issued customer prices. The separately reconciled printed-letter corpus has unknown customer outcomes. Neither one validates current material, routing, labor, lead time, or current sell price. Historical analogs require exact revision/material/process/UOM and quantity-break review; ambiguous or absent evidence holds the line. An approved private operator can run the canonical estimator/order CLI with an explicitly selected verified register and keep its request, source analogs, draft, and receipt outside the tracked workspace. A complete internal priced-order proposal still requires named human review of costs, evidence, shipping/tax, terms, and customer-safe messaging; no automated delivery or order booking is enabled.

The ≥90% completed-quoting goal is **not established** by this workspace. The existing replay measures historical price prediction on a frozen basis, not end-to-end completed, correctly reviewed orders. No claim of accuracy improvement follows from mounting Ars Umbris, connecting Polygres, or making skills discoverable. Measure and review the separate completion gate before any production release.

The `keller_quote` tool is the controlled internal draft path, not a release mechanism. It requires an explicit public corpus ID, an order request satisfying the estimator's `OrderRequest` contract, and a named human reviewer; it reuses the local order CLI with explicit operator price/cost inputs or the selected read-only customer-PDF register. It preserves blocked lines and returns structured `order`, `markdown`, `review`, state/blockers, and opaque references to persisted private artifacts. **The response itself contains private customer/cost evidence** and must stay in approved internal channels; don't paste it into a public graph node or customer message. It performs no database write or hosted model call. Treat a `PRICED_REQUIRES_REVIEW` result as an internal calculation awaiting approval, not as a quote sent to a customer.

### Read a selected PDF page without mistaking text for geometry

The optional `pdf_text` source action requires Linux and distro-maintained Poppler `pdfinfo`/`pdftotext` on the source-tool host. Install with `sudo apt-get update && sudo apt-get install -y poppler-utils` on Debian/Ubuntu; the managed Python setup does not install system binaries. Missing tools produce an explicit unavailable error, not an empty page. No cloud upload or model call occurs.

```json
{"action":"pdf_text","source_set":"pdfs","path":"synthetic-drawing.pdf","page":1,"limit":4096}
```

Use only an exact owner-approved relative path, with the same no-symlink/confinement rules as other source reads. `page` is explicit and one-based; output includes measured `citation.pdf_sha256`, `page_count`, `text_sha256`, status and bounded layout text. `offset` and `limit` count **Unicode characters**, not PDF bytes. For page > 1 or offset > 0, supply `expected_pdf_sha256`; for offset > 0 also supply `expected_text_sha256` from that same page. Continue `next_offset` until `has_more` is false before treating the page's extracted text as fully read. A different page has its own text hash. Hash changes require rereading, not combining incompatible output.

PDFs are limited to 32 MiB/10,000 pages, one selected page per call, 4,096 characters per response and <128 KiB extractor output. Each child has a four-second wall limit, two-second CPU limit and 512 MiB address-space limit. Encrypted, malformed, changed, warning-producing or resource-exceeding inputs fail closed without returning partial text. Hashes attest local bytes, not external authenticity or completeness of extraction. Parser limits are not an OS security sandbox.

`no_extractable_text` means OCR or visual review is needed; it does not distinguish blank, scanned, outlined or illegible content. Text extraction does not perform OCR, resolve overlapping dimensions, interpret CAD, execute document instructions, authenticate revision/applicability or calculate costs. Even `text_extracted` may miss symbols or have wrong reading order. Carry the PDF hash/page into retained evidence and separately reviewed engineering facts; retain unknowns/conflicts. These operator source reads do not expand blinded-worker allowlists or admit target quote PDFs.

### Discover manufacturing catalog candidates without prior IDs

`dbf_schema.catalog_lookup` advertises `dbf_catalog` only for the approved MATERIAL, OPERATIO and FORMULA definition shapes. Use it to discover candidate IDs for a new RFQ, not to select an applicable cost automatically. Synthetic request shape:

```json
{"action":"dbf_catalog","source_set":"fabritrak","path":"OPERATIO.DBF","query":"drill","limit":5}
```

Resolve the real relative path from the owner-bound source inventory. Omit `query` for a bounded browse, or use a case-insensitive literal substring (1..80 characters) over fixed fields: MATERIAL `ID/NAME/OTHERNAME`, OPERATIO `OPER_ID/NAME`, FORMULA `FORM_ID/FORM_NAME`. It does not search monetary fields, memo text or executable expressions. Case-insensitive discovery is not case-insensitive identity: subsequent `dbf_rows.record_id` remains exact. Unknown/mismatched schemas, quote-history table names and caller-selected predicates are rejected.

The existing five-row, 20,000-record, 16-MiB scan and response-size limits apply. Follow `next_offset` with the same query and `expected_dbf_sha256` (mandatory for nonzero catalog offsets); duplicate IDs remain separate physical records, deleted records are skipped, and hash changes fail closed. Finish with a bounded exact-ID/memo read where needed. Record source hashes, locators and unresolved candidates; no automatic join, unit/COST interpretation, current-cost assertion or customer release occurs. Blinded evaluation profiles still cannot call the source tool.

## Current runtime and workspace verification

The [2026-10-07 verification receipt](../artifacts/keller-workspace-verification-2026-10-07.json) records the coherent `0.0.2-alpha` build and completed native check. A cold engine became fully ready in 34.131 seconds before Electron opened the overview. The native graph resolved all 39,975 unique document instances and all 39,975 archive edges, plus 513 outgoing references across 65 other checked records. The overview and experiment-ledger navigation through the native document-tabs chooser rendered with zero own diagnostics, renderer errors or host conditions.

Both CI verification commands pass locally: the repository check covers 98 estimator tests, 182 Python tests, 54 script tests, the TypeScript build/typechecks, compiled offline smoke and 11 synthetic order tasks; the database check covers 28 tests against an isolated PostgreSQL 16 cluster. The scoped plugin typecheck also passes. GitHub did not start either hosted job because of account billing or spending limits, so these are local results, not green hosted CI. The synthetic tasks remain seven completed fixtures, two correct holds and two validation rejections, not live quoting-accuracy evidence.

## Earlier verified scope and remaining gate

The earlier `0.0.1-alpha` native host rendered the Keller layout with 16 panes; opening the source catalog through the UI routed through the tabs intent. The live engine resolved the startup/layout and had no own diagnostics or event conditions. The standard stdio MCP graph and Polygres read connections passed protocol checks, and native tool calls covered the 11-tool profile, Polygres search/page/prices, an original PDF, DBF schema and a supplemental formula record, a synthetic priced internal draft totaling 285.96, a blocked draft with null total, and denial of path traversal and unauthorized Bash. That earlier local full verification passed 86 TypeScript tests, 74 Python tests (16 + 18 + 40), 26 script tests, and 11 synthetic order scenarios (seven completed, two correct holds, two validation rejections), plus plugin `tsc` and frozen original CSV/JSON/evalset checks. These checks establish wiring and refusal behavior, **not** live price accuracy, end-to-end completed-quote performance, or the ≥90% goal. See the [MCP workflow results](mcp-workflow-evaluation-results.md) for the separate reissue evaluation and its limitations.

The native session launcher currently reaches a Codex login in the Desktop. A human must complete that login there before a **native Codex** exchange can be tested; this does not require exposing or adding an API secret. External agents using `Keller Workflow` bring their own model access and need only the headless engine/MCP connection for tool calls. The pinned native host E2E harness/API was used for host verification; no separate named `testing-au-host-electron` skill was present. Native authentication is not a blocker for stdio MCP evaluation.
