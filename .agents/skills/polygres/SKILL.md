---
name: polygres
description: Query Keller's Polygres legacy mirror and explicitly selected, additive customer-PDF evidence corpus; use for safe connections, read-only retrieval, schema, and capacity limits.
---

# Polygres: two independent Keller price bases

The normalized legacy `customers`, `parts`, `quotes`, `quote_qty_breaks`, `quote_letters` and `quote_letter_lines` mirror the frozen internal-calculation register. `estimates`/`estimate_lines` are generated drafts, not historical source rows. `quotes.status='won'` is merely an unverified posted-history label; `open` is not a verified loss. The additive document corpus stores reconciled **recorded customer quotation** prices with outcome `unknown`; price verification alone does not authenticate issuance. Never silently join the two bases into a price curve or use text search as numeric authority. See [the register guide](../keller-quote-register/SKILL.md).

## Bounded evidence calls

Follow the [canonical quote procedure](../keller-quote-estimator/SKILL.md): draft once and inspect returned contributors before lookup. Plan one deduplicated exact evidence phase using the explicit `corpus_id` and exact part/quote/source keys shared across lines, not one mandatory lookup per line. Within it, allow bounded page/memo continuations and a named price-critical lookup with a source/key, field, page/record budget and stopping condition. Parallelize only independent reads; do not repeat identical calls, broaden indiscriminately or fish across corpora. Search finds pages, not numeric authority.

Keep price basis explicit: `customer_quote_pdf` is reconciled recorded-price evidence with unknown outcome; `internal_quote_calculation` is historical nominal calculation evidence; neither proves current cost. Preserve returned finite amounts as `NUMERIC_PROVISIONAL`, separately from adoption/readiness. Explicit scope conflicts block transfer; unknown current costs prevent supported margin claims, not historical comparison. Evidence without usable price remains `PRESENT_BUT_NO_USABLE_PRICE`; no evidence is `NONE`. Only after relevant retained evidence is exhausted, consolidate remaining critical questions and unresolved shipping/tax. Supported estimates/ranges can support prospective costing without paid/closed-job proof; missing cost is never zero.

Use quote pages and continuations for specification/terms, and provenance-labeled CSV/DBF fields for revision/drawing/RFQ and memo discovery. Inherited comments are not independently verified printed scope. A blank material field is not absence of material evidence; a quote-filter miss is not corpus-wide absence. An authorized operator may inspect other retained document kinds for a named specification/purchasing question; supplier POs remain purchasing evidence, never customer-price breaks. Only use fields/actions exposed by the deployed contract. Existing blinded scopes do not gain richer projections, archive roots or downstream outcomes from this guidance.

## Safe read access

Keller Workflow uses the CC stdio transport without launching Claude. External agents can invoke its graph, evidence and quote tools using their own model connection; the host's native Codex CLI login is not required.

If Keller MCP discovery fails before a tool response, compare --runtime-root exactly with the operator's pinned launch command before retrying. Do not repeat an unverified path unchanged or infer that model login is required.

Use the explicitly selected `Keller Workflow` profile for an external MCP-capable agent, or `Keller Codex` for the optional native host session. Both expose the same scoped evidence and draft tools; the transport does not choose the evaluating model. The [workspace guide](../../../docs/arsumbris-workspace.md) documents discovery and private per-call audit traces.

Check whether the existing configured `POLYGRES_DIRECT_URL`, `POLYGRES_DATABASE_URL`, and expected database name are available in the current runtime before requesting access. Do not print a DSN/password or put one in a report. The direct URL is for psycopg and `scripts/document-evidence-db.py`; the pooled URL may include `pgbouncer=true`, which libpq does not accept. For remote evidence CLI access, the **effective direct URL must contain** `sslmode=verify-full` and `sslrootcert=/etc/ssl/certs/ca-certificates.crt`; the CLI enforces this plus `--expected-database`. Use an approved connection string assembled without displaying its value. In standalone SQL, use read-only transactions, parameterized values and a confirmed database identity. No control-plane/MCP registration, plan change, reimport, or credentials refresh is needed to read the existing corpus.

Select an actual public `corpus_id` rather than guessing the newest ingestion. `keller_polygres({action:"corpora"})` now includes the immutable corpus counts and `ingested_at` snapshot timestamp; use that timestamp only to identify a snapshot, never as quote chronology. A read-only discovery query is:

```sql
select corpus_id, document_count, page_count, price_count, ingested_at
from document_corpora order by ingested_at desc;
```

The timestamp helps identify a snapshot; it is **not** quote chronology or a global latest pointer. Choose the explicit approved corpus from the request and provenance; ask the owner only if that choice is ambiguous, and never infer "latest" from ingestion time. Then use the CLI from repository root with a private, **new** output path (read-only commands; do not use `load --apply`):

In the Ars Umbris `Keller Codex` profile, prefer `keller_polygres` for bounded read-only `corpora`, `search`, `page`, and `prices` retrieval: pass the explicit corpus for every action except `corpora`; use exact part/quote filters for prices and a cited source path/page number for page text. It does not expose arbitrary SQL or the full CSV export. `keller_quote` performs its own read-only full-register export before an offline internal order draft, while the standalone CLI below remains available to an authorized operator for private analysis/evaluations. Neither path writes Polygres or authorizes release.

Keller MCP prices/search accepts at most 50 rows per call. When a lookup rejects its pagination arguments, correct them within the documented bounds before concluding that eligible evidence is unavailable or out of scope.

```sh
python scripts/document-evidence-db.py search 'synthetic bracket' \
  --expected-database "$DB_NAME" --corpus "$CORPUS_ID" --kind quote --limit 20
python scripts/document-evidence-db.py prices --part 'SYNTHETIC-PART' \
  --expected-database "$DB_NAME" --corpus "$CORPUS_ID"
python scripts/document-evidence-db.py export \
  --expected-database "$DB_NAME" --corpus "$CORPUS_ID" --out "$NEW_PRIVATE_CSV"
```

`search` first uses document-grain GIN candidates, then filters at **individual page** FTS, so terms spread over separate pages do not falsely match. Results cite page/PDF hashes for review, not verified prices. `prices` validates original CSV fields and their consistency with recorded source-document metadata; it does **not** reopen private PDFs to rehash them. `export` validates the **complete** reconstructed CSV and its original digest, including multiline records. Export before estimator/eval runs and pass that path as `--register`. Do not assemble an incomplete CSV by querying only typed SQL columns: `verified_document_prices` stores typed prices, original `raw_csv`, and document joins, **not** `original_row` JSONB. See [document evidence operations](../../../docs/polygres-document-evidence.md).

## Schema and historical retrieval

The additive physical tables are `document_corpora` (immutable public `corpus_id`, internal numeric `corpus_key`), `evidence_documents` (PDF, independent Poppler and original AnyDoc status/hash), `evidence_page_sets` (document-grain hash-checked JSONB page arrays), and `verified_document_prices` (typed values plus raw CSV). `evidence_pages` is a read-only ordinal view, **not** a fifth physical table. All document SQL must constrain `corpus_key` through the **explicit** selected `corpus_id`. A verified price is traceable to its joined source document; never infer one from invoice/PO text.

Legacy retrieval remains available separately: `parts.fts` and `quotes.fts` have GIN indexes; trigram supports fuzzy part/drawing/customer lookup. pgContext collections `parts_desc` and `quote_comments` use 512-dimension cosine **distance** (smaller is closer); `graph` links quotes to customers, parts, and re-quote predecessors. These layers were built for legacy rows, **not** document pages or verified prices. Query them with limits and source/cutoff checks, never claim semantic resemblance proves revision, process, material, or UOM equivalence. [Data analysis](../keller-data-analysis/SKILL.md) covers grain and outcome-safe aggregation.

## Capacity and change boundary

As verified 2026-09-28, the additive import covered 39,975 PDF records and 75,096 pages across the whole corpus. Separately, 42,873 verified customer-quote quantity breaks came from **7,845 price-source PDFs**; 7,845 is not the whole-corpus PDF denominator. Poppler produced text for 39,960 records, 14 were blank, and one zero-byte PDF failed. It independently recovered searchable text for 164 original AnyDoc failures while preserving their original status and hashes. All eight original core tables remained full-row-hash identical and both vector collection counts were unchanged. The database occupied 500,291,251 bytes (~477.1 MiB), leaving only ~22.9 MiB nominal room below the documented 500 MiB limit. These are dated observations, not guaranteed present-day capacity. Recheck actual database size/allocation, physical relation/index growth, and the capacity policy before **any** future write; a second full corpus does not fit without an explicit capacity decision. Document evidence was not registered in graph or pgContext. Read/query permission is never permission to import. Any approved import uses `scripts/document-evidence-db.py` with measured growth, database guard, TLS and post-write row/hash proofs, not legacy `scripts/load.py`; never modify the frozen register to make room.
