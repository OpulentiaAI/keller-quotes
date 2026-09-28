# Additive document evidence in Polygres

This mirror does not replace `quotes.csv` or any legacy Polygres quote, break, embedding, graph, or estimate. It stores independent, page-attributed Poppler layout text for every source PDF and only the separately validated customer-price CSV rows. The PDFs, AnyDoc Markdown, audits, and original files remain in private storage; never commit or upload them. Neither an invoice nor a posted quote proves payment, an order, or a verified win. The verified price rows retain `status=unknown`, `price_basis=customer_quote_pdf`, and the five-decimal source precision when present. Current manufacturing costs are not inferred.

## Build a private, immutable bundle

Use Python with `psycopg[binary]` installed and Poppler `pdfinfo`/`pdftotext` on PATH. This preparation uses neither a database nor a hosted OCR/embedding API. The output path must be new and outside every input. It processes the entire verified PDF inventory, including AnyDoc failures and blank pages, and keeps its source proofs unchanged.

```sh
python scripts/document-evidence-db.py prepare \
  --source-dir "$PDF_SOURCE" \
  --source-manifest "$SOURCE_MANIFEST" \
  --transcripts "$TRANSCRIPTS" \
  --price-bundle "$DOCUMENT_REGISTER_BUNDLE" \
  --out "$NEW_PRIVATE_EVIDENCE_BUNDLE" --workers 4
```

The resulting `manifest.json` pins each input manifest/bundle digest, selected CSV digest and header/column order, original AnyDoc version/fingerprint, Python and Poppler versions, prepare-script digest, row counts, and hashes for `documents.jsonl`, `pages.jsonl`, and `prices.jsonl`. Its content digest is the corpus ID. Page text comes from independent `pdftotext -layout`, never the AnyDoc Markdown; a failed extraction has zero pages and stays in the document denominator with a bounded error reason. Each PDF's filename hint is separate from a conservative unambiguous-content header classification. Form feeds define page boundaries, with an empty page retained as an empty row. The verified-price JSONL carries every original CSV field and its exact physical UTF-8 CSV record, so multiline cells and original numeric spellings roundtrip byte-for-byte. A new bundle must be rebuilt instead of editing an existing one.

## Local capacity validation before any live import

Only use a disposable local database for implementation tests. The script accepts a direct URL through `POLYGRES_DIRECT_URL` only, and every database operation demands `--expected-database` matching `current_database()`. Its default load is read-only: it verifies the entire prepared bundle and reports row counts and existing database size without DDL.

```sh
POLYGRES_DIRECT_URL="$LOCAL_DIRECT_URL" python scripts/document-evidence-db.py load \
  "$NEW_PRIVATE_EVIDENCE_BUNDLE" --expected-database "$LOCAL_DB_NAME"

POLYGRES_DIRECT_URL="$LOCAL_DIRECT_URL" python scripts/document-evidence-db.py load \
  "$NEW_PRIVATE_EVIDENCE_BUNDLE" --expected-database "$LOCAL_DB_NAME" \
  --expected-growth-mib "$MEASURED_GROWTH_MIB" --storage-budget-mib "$LOCAL_BUDGET_MIB" --apply
```

Measure actual full-bundle relation and index growth locally before deciding whether the live 500 MiB Nano budget permits import; `--expected-growth-mib` is an operator-supplied guard, not an estimate made by the program. The script checks projected headroom before writing a **new** corpus and total database size inside the import transaction. A live import additionally requires owner approval and a direct URL configured with `sslmode=verify-full` and `sslrootcert=/etc/ssl/certs/ca-certificates.crt`; nonloopback weaker TLS settings are rejected. No graph or pgContext registration is performed. The additive migration and all rows are inserted under advisory lock `57841433` in one transaction; a missing legacy quote, invalid proof, or exceeded budget rolls back. Identical corpus replay verifies metadata, row counts, page/document contents and price rows and skips without changing the ingestion time or reserving growth again. Every query requires an explicit corpus ID; importing an older bundle cannot switch a global latest-corpus pointer.

The four physical tables are `document_corpora` (public hash and internal key, bundle proofs and source CSV format), `evidence_documents` (compact document ID, PDF/AnyDoc provenance and status), `evidence_page_sets` (one lossless JSONB array of page text and SHA-256 per document, including an empty array for an unextractable PDF), and `verified_document_prices` (typed positive quantity/full-precision prices, existing-quote/source-document foreign keys, and exact original CSV record). `evidence_pages` is a read-only, ordinal page view over the arrays for citations and replay. A SQL integrity function checks every page's text and computed SHA-256. The document-grain expression GIN index supplies candidate search; an individual-page FTS filter then rejects matches whose terms occur only across separate pages. Page sets and prices use a 512-byte TOAST target; neither stores a materialized FTS vector or duplicate source hashes/paths. Read-only prices, export, and corpus replay parse the original CSV record and compare every typed price/date/identity against its joined document. No PDF binary or redundant AnyDoc transcript is stored. Verify total and individual **physical relation** sizes (including `evidence_page_sets`, not its view) after a local load with `pg_total_relation_size` and `pg_database_size` before any live plan.

## Read-only evidence retrieval and export

```sh
POLYGRES_DIRECT_URL="$DIRECT_URL" python scripts/document-evidence-db.py search \
  'anodized bracket' --expected-database "$DB_NAME" --corpus "$CORPUS_ID" \
  --kind quote --quote SYN-001 --limit 20

POLYGRES_DIRECT_URL="$DIRECT_URL" python scripts/document-evidence-db.py prices \
  --part SYN-PART --expected-database "$DB_NAME" --corpus "$CORPUS_ID"

POLYGRES_DIRECT_URL="$DIRECT_URL" python scripts/document-evidence-db.py export \
  --expected-database "$DB_NAME" --corpus "$CORPUS_ID" --out "$NEW_PRIVATE_CSV"
```

Search is parameterized English FTS, scoped to a corpus, bounded to at most 100 hits, and returns PDF path/hash plus page number/hash for review against the original private PDF. A kind filter is based on recognizable content, not filename. The quote filter only finds pages from documents linked to verified-price rows. Exact part/quote price lookup returns original row fields and source hashes; it does not invent prices from arbitrary invoice text. Export requires a new file, orders records by original CSV row number, and checks the exact original CSV digest before leaving it. Keep exported rows private and review original PDF tables before sending any quote.
