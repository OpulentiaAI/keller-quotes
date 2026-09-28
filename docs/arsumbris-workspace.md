# Keller Ars Umbris workspace

This repository is the `keller-quotes` entry repo for the pinned Ars Umbris `0.0.1-alpha` runtime. `.arsumbris/repo.yaml` declares the type peers used by the layout, skill/profile instances, and MCP tools; `.arsumbris/workspace.yaml` edits this repository and discovers the `host-bundle` and `mcp-bundle` closures. The host opens `workspace-layout.yaml` into a branded evidence reader, source tree, and `Keller Codex` session launcher. The public [[source-catalog]] and [[organization-catalog]] are typed indexes, not replicated private records.

## Install, build, and open

Use an authorized Linux desktop account with Git access to the locked Ars Umbris repositories, Node 24, npm, pnpm honoring the host's `packageManager: pnpm@11.1.1`, Rust/Cargo, native compiler tools, and Python with `venv` and pip available. The GUI also needs a working desktop display and Electron's system libraries. Setup does not install these system prerequisites or change their versions. It refuses a mismatched existing checkout instead of resetting it; move or repair that checkout explicitly before retrying.

Install Codex CLI separately and pass `--codex-binary /absolute/path/to/codex` to setup if it is not already registered in Ars. This session verified CLI `0.154.0` at `~/.capy/work/keller-au-bootstrap/codex-cli/node_modules/.bin/codex`. The option registers that executable, not authentication; an existing binary entry is preserved. An approved Codex account must sign in through the host's session terminal before a model-driven test.

From the repository root, the default runtime location is `~/arsumbris`. This session used the already pinned local set at `~/.capy/work/keller-au-bootstrap/runtime`; pass the same override to setup and every launch command when reusing it:

```sh
node scripts/setup-arsumbris.mjs --runtime-root "$HOME/.capy/work/keller-au-bootstrap/runtime"
node scripts/start-arsumbris.mjs host --runtime-root "$HOME/.capy/work/keller-au-bootstrap/runtime"
```

Setup verifies the coherent `0.0.1-alpha` lock, builds the runtime and Keller host overlay, prepares the managed Python/estimator dependencies, registers the workspace, and writes the ignored MCP-client config. It does **not** fabricate private source bindings or authenticate Codex. Do not substitute upstream `main`. For a normal GUI launch, start **host alone**: it owns/starts the engine for `AU_ENTRY` (the absolute `keller-quotes` folder, not the layout YAML). Starting the engine separately first can cause an already-running-engine error. If running headless MCP instead of the GUI, start `engine` and then `mcp` as separate long-lived commands with the same `--runtime-root`, and use `.keller-local/arsumbris/mcp.json` with the approved stdio client. The host's `--software-rendering` option is available when GPU rendering is unavailable. These commands do not start a customer workflow or hosted model call.

The host's default session profile is [[Keller Codex]]. It selects the pinned Codex adapter, five typed `mcp.skill` wrappers, the minimal standing safety inject, graph read tools, `mcp.tool.keller_polygres`, bounded read-only `mcp.tool.keller_sources`, and the root-owned `mcp.tool.keller_quote` for internal requires-review order drafts from explicit operator costs or read-only corpus evidence. `[[Keller Graph Readonly]]` selects only graph reads; `[[Keller Polygres Readonly]]` selects only the bounded database read tool. Those two narrow profiles use the CC adapter for the generic stdio MCP bridge (`node scripts/start-arsumbris-mcp-client.mjs --profile 'Keller Graph Readonly'` or `--profile 'Keller Polygres Readonly'` after starting engine and MCP), and supply no skills or standing injects. All three use `nativeToolAllowlist: []` to prevent a native shell from bypassing their gates; none grants credentials. Each quoting wrapper points to its **canonical** `.agents/skills/<name>/SKILL.md` and asks the agent to read it through `read_file_pinned` before acting. If the source skill or MCP service cannot be read, stop or hand off to an operator. The wrapper body is not a substitute for the canonical procedure.

To inspect the graph, ask `au_instances_of` for `mcp.skill::au-mcp-sdk`, `agent-profile::au-mcp-sdk`, `keller.source::keller-quotes`, and `keller.organization::keller-quotes`; use `au_members`/`au_type` for discovery, resolve the selected instance, and inspect `au_diagnostics`. The profile includes `au_files`, `au_follow`, and `read_file_pinned` for source navigation. A dependency listed in `repo.yaml` gives permission to reference its types; the workspace's `discover` list mounts the UI/MCP bundles. These files and any device registry entries are separate concerns.

## Private evidence binding

The GUI starts its MCP daemon when **New session** is selected; merely opening the layout does not start the agent layer. After that, or after starting both headless services, run `node scripts/verify-arsumbris-mcp.mjs --runtime-root <runtime-directory>` to check the two scoped standard MCP connections and perform a live read-only corpus lookup. `--skip-corpora` skips that database read; it is not database-access verification. The smoke check fails on unresolved graph errors. The generic stdio bridge uses the upstream CC transport without launching Claude or changing the Codex model selection.

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

The `fabritrak` binding must contain both the primary source snapshot and supplemental FORMULA/BOM files when those are approved for inspection; binding only the primary DBFs hides the manufacturing supplement. `KELLER_PDF_CORPUS_DIR`, `KELLER_DBF_SNAPSHOT_DIR`, `KELLER_DOCUMENT_EVIDENCE_DIR`, and `KELLER_SOURCE_AUDIT_DIR` in the catalog name locator roles, not necessarily exported environment variables. Verify paths, manifest hashes, and access rights on each host before using raw files. `mcp.tool.keller_sources` provides closed-set bounded read-only `sets`, `list`, `read`, `dbf_schema`, and exact-quote `dbf_rows`; it cannot mutate a source, and reading historical material/routing records does not prove present costs or times. The PDF archive, transcript summary and records, verified derivative, and DBF audit have different failure accounting; missing or failed records must stay visible rather than disappearing from a denominator. A graph catalog entry is a pointer, not a claim that binaries are mounted or that a PDF viewer can open them directly.

For the read-only database tool, bind the existing `POLYGRES_DIRECT_URL` privately, enforce the documented TLS/database identity guard, and explicitly select corpus `5089cd30b1b51f3903c6f16459dcf883a36137156086fc105220f594faf64a90` in database `app_peb68ccd10bc4e4ea3b43852`. `corpora` discovers public IDs; `search` finds page citations, `page` reads a cited page, and `prices` returns verified customer-PDF prices by exact part or quote. Search text is not a price. The tool accepts no SQL or write operation and bounds output. Consult `.agents/skills/polygres/SKILL.md` and `docs/polygres-document-evidence.md` for historical basis and access constraints. The direct URL is secret and must never appear in the graph, logs, reports, Git, or a customer artifact. The pooled URL is not a libpq substitute.

## Quoting and release boundary

For DBF quote lines, `dbf_rows` takes an exact `quote_no`. For material, operation, and formula catalogs, pass an exact `record_id` instead; the reader uses only the table's single `ID`, `OPER_ID`, or `FORM_ID` column. Both filters together are rejected. Each call remains bounded to 20,000 scanned records and at most five returned rows, with continuation; memo fields remain pointers rather than decoded memo text.

The committed `quotes.csv` and `quotes.json.gz` are frozen internal-calculation breaks, not necessarily issued customer prices. The separately reconciled printed-letter corpus has unknown customer outcomes. Neither one validates current material, routing, labor, lead time, or current sell price. Historical analogs require exact revision/material/process/UOM and quantity-break review; ambiguous or absent evidence holds the line. An approved private operator can run the canonical estimator/order CLI with an explicitly selected verified register and keep its request, source analogs, draft, and receipt outside the tracked workspace. A complete internal priced-order proposal still requires named human review of costs, evidence, shipping/tax, terms, and customer-safe messaging; no automated delivery or order booking is enabled.

The ≥90% completed-quoting goal is **not established** by this workspace. The existing replay measures historical price prediction on a frozen basis, not end-to-end completed, correctly reviewed orders. No claim of accuracy improvement follows from mounting Ars Umbris, connecting Polygres, or making skills discoverable. Measure and review the separate completion gate before any production release.

The `keller_quote` tool is the controlled internal draft path, not a release mechanism. It requires an explicit public corpus ID, an order request satisfying the estimator's `OrderRequest` contract, and a named human reviewer; it reuses the local order CLI with explicit operator price/cost inputs or the selected read-only customer-PDF register. It preserves blocked lines and returns structured `order`, `markdown`, `review`, state/blockers, and opaque references to persisted private artifacts. **The response itself contains private customer/cost evidence** and must stay in approved internal channels; don't paste it into a public graph node or customer message. It performs no database write or hosted model call. Treat a `PRICED_REQUIRES_REVIEW` result as an internal calculation awaiting approval, not as a quote sent to a customer.

## Verified scope and remaining gate

The pinned native host rendered the Keller layout with 16 panes; opening the source catalog through the UI routed through the tabs intent. The live engine resolved the startup/layout and had no own diagnostics or event conditions. The standard stdio MCP graph and Polygres read connections passed protocol checks, and native tool calls covered the 11-tool profile, Polygres search/page/prices, an original PDF, DBF schema and a supplemental formula record, a synthetic priced internal draft totaling 285.96, a blocked draft with null total, and denial of path traversal and unauthorized Bash. Local verification passed 86 TypeScript, 60 Python, 19 script, and 11 scenario checks, with the final source-reader change covered by a fresh 26-test workspace/tool rerun. These checks establish wiring and refusal behavior, **not** live price accuracy, end-to-end completed-quote performance, or the ≥90% goal.

The session launcher currently reaches a Codex login in the Desktop. A human must complete that login there before an authenticated agent exchange can be tested; this does not require exposing or adding an API secret. The pinned native host E2E harness/API was used for host verification; no separate named `testing-au-host-electron` skill was present. Authentication remains an agent-session gate, not a blocker for the already completed graph, host, MCP, and native protocol tests.
