# Local PDF evidence for quote drafts

The original `quotes.csv` and `quotes.json.gz` are preserved source extracts. Their sell prices come from internal `QUOTQTYS.UNIT_SELL` calculations, which can differ from customer quote letters. This workflow creates a **separate** customer-price register and carries PDF provenance into reviewable estimates and order proposals. It does not send quotes, update FabriTRAK, refresh Polygres, or activate a scheduler.

## Evidence and limits

The September 27–28, 2026 read-only transfer covered all 39,975 PDFs under `C:\Vftw`: 2,634,657,836 bytes before compression. The original inventory, source-side before/after hashes and modification times, archive hash, and every extracted file's size and SHA-256 reconciled. The inventory includes 14,718 quote-letter filenames, 11,405 invoices, 11,326 supplier-PO filenames, and other documents. A filename is a classification hint, not proof of business meaning.

Eight deliberately selected quote PDFs contained 40 quantity/price/extension rows. All 40 matched the letter-line prices after truncating the displayed unit price to two decimals and rounding the extension from the full-precision price; only eight matched the internal calculation price. Five documents were selected for known discrepancies and three were the newest saved letters, so **this is not a random accuracy estimate**. A separate check of PDFs where `PRICE` and `QUOTEPRICE` differ found 16 distinguishable rows supporting `PRICE`; the builder still verifies each document rather than assuming every stored field is authoritative.

AnyDoc `0.2.4` is a local transcript generator, not a reliable price-table parser. In the eight-file prototype, seven PDFs converted and one raised `NeedsOcrError` despite containing text readable by Poppler. One converted document separated all 15 quantities from its price/extension table. Merely finding the expected numbers in Markdown would have missed that structural defect. Independent `pdftotext -layout` extraction verifies ordered price rows; an OCR transcript can qualify only under the stricter coverage and reconciliation checks below.

Source freshness and manufacturing scope remain separate limits. The latest original quote and modification dates in the verified `QUOTEN` snapshot are August 12, 2026. Formula IDs resolve, but populated operation variables and stored rates do not prove current costs: the source lacks independent positive operation-time totals, some inputs are zero or missing, and source formulas include division-by-zero cases. No new-part labor/material cost engine or current-cost guarantee is implied by this work.

## Install on a private processing machine

Use Python 3.12, Poppler (`pdfinfo`, `pdftotext`, `pdftoppm`), and Tesseract with English language data. Run both document-processing stages on Linux rather than on the live quoting workstation: subprocess deadlines use POSIX process groups, and atomic bundle publication uses Linux no-replace renaming. The resulting CSV remains usable by the existing cross-platform Node worker.

```sh
python3 -m venv "$HOME/.venvs/keller-documents"
. "$HOME/.venvs/keller-documents/bin/activate"
python -m pip install -r requirements-documents.txt
```

`firecrawl-anydoc==0.2.4` corresponds to tag `v0.2.4`, commit `42bf1c5ecdde9eb0d96d6bd75a9e6698cf93b14c`. The package is pinned rather than following a branch that can contain different code under the same version string. Conversion always passes `ocr="reject"`; no Firecrawl API key, hosted OCR, gateway call, or document upload is used. `--local-ocr` opts into local Poppler/Tesseract fallback only.

Keep source PDFs, DBF/FPT copies, transcripts, manifests, generated registers, and evaluation artifacts outside the checkout in private storage. Do not commit them or attach customer documents to a public PR. Files under a cloud workspace are not a durable deployment; move an approved release bundle into owner-approved persistent private storage before binding a scheduler.

## Transcribe the complete verified inventory

The source manifest has `schema_version: 1`, `file_count`, `total_bytes`, `archive_sha256`, `archive_bytes`, `all_source_hashes_and_mtimes_unchanged: true`, and `files` entries with `path`, `bytes`, `sha256`, and timezone-qualified `modified_utc`. It records source-side integrity checks; do not manufacture that flag for an unchecked transfer. Extract into a new private directory after verifying the archive hash, preserving modification times. Windows separators and either case of hexadecimal hashes are accepted.

With absolute private paths assigned to the variables below:

```sh
python scripts/transcribe-pdfs.py \
  --source-dir "$PDF_SOURCE" \
  --source-manifest "$SOURCE_MANIFEST" \
  --out "$TRANSCRIPTS" \
  --workers 4 --timeout 120 --local-ocr
```

Before conversion, the script checks the complete inventory, each source hash/size/mtime, unsafe paths, and symlinks. Each PDF first goes through AnyDoc, then page-coverage checks. OCR fallback identifies each locally OCR'd page; mixed documents preserve the other pages through layout extraction. Empty, encrypted, malformed, blank-after-OCR, incomplete, and timed-out documents remain explicit failures rather than successful empty transcripts. The deadline applies to each document, so a large manual can require a longer bounded rerun.

`summary.json` accounts for every input and maps paths to private `records/<key>.json` files; successful records point to hashed Markdown transcripts. Exit 0 means every document succeeded, exit 1 means the run completed with held/failed documents, and exit 2 means input/configuration validation failed. Inspect the records before claiming complete transcription. A successful transcription is not a claim that every number or drawing detail was recognized correctly.

Rerun the same command to resume. Reuse requires matching source, transcript, page-coverage, OCR-policy, script, and toolchain fingerprints. Changed or damaged evidence is reprocessed; failed documents are retried. Preserve failed-document records and report their counts instead of dropping them from the denominator.

## Build a separate customer-price register

Only run the builder after the transcription summary has been written:

```sh
python scripts/build-document-register.py \
  --register quotes.csv \
  --dbf-dir "$DBF_SNAPSHOT" \
  --source-dir "$PDF_SOURCE" \
  --source-manifest "$SOURCE_MANIFEST" \
  --transcripts "$TRANSCRIPTS" \
  --out "$NEW_REGISTER_BUNDLE"
```

The new output directory contains `document-quotes.csv`, `evidence-manifest.json`, and `private-document-audit.json`. The manifest pins the input register, source DBFs/memos, source inventory, transcription records, transcripts, and implementation digests. The audit records document dispositions and independent verification-text hashes. These files belong together in private storage.

The builder deliberately accepts a limited, auditable subset:

- A quote-letter filename must agree with the document's quotation title, letter number, quote ID, part identity, and inquiry date, and resolve to an unambiguous source letter line and original quote group. An observed `By:`/footer date that conflicts with the inquiry date, or is malformed or ambiguous, holds the document. A footer without an observed date remains supported but does **not** verify its printing chronology. Multi-item/multi-quote or inconsistent identities are held rather than guessed.
- Every source quantity break must match exactly one ordered printed quantity/unit-price/extension row. Duplicate, missing, extra, ambiguous, or unreconciled rows hold the document. Text PDFs use independent layout extraction; fully OCR'd PDFs require complete page attribution before their transcript can be used.
- A usable `PRICE` or `QUOTEPRICE` must reproduce both the truncated displayed unit price and the rounded extension with decimal arithmetic. Full stored price precision is retained; the displayed unit price is never substituted for it. Different fields that cannot be distinguished from the printed evidence are held.
- Only one accepted letter supplies a quote/item curve. The latest accepted letter is selected by its DBF letter date; same-date ambiguity is held. The letter date remains the price's recorded evidence date, and later source revision dates remain visible to cutoff filtering. Agreement of observed dates is a consistency check, not proof of original issuance or availability at that time; a print date is not silently substituted for the letter date.

Supplier POs, invoices, certificates, manuals, and other transcripts remain available for separate analysis but never enter the customer-price register. Internal cost, markup, and alternate-price fields are cleared in the derivative. Outcome is `unknown`: printing a letter or posting quote history does not prove a won order. A smaller verified register is preferable to silently filling gaps with another price basis.

Printed quantity, unit-price, and extension matches verify the numeric amounts, not the price-bearing PDF's historical availability. This validation applies only when building a **new** bundle: existing built corpora retain their prior contents and dates, so a code fix does not repair or regrade them. Review their chronology separately before relying on historical cutoff claims.

## Use the evidence in the existing workflow

Pass the derivative explicitly; the default register is not replaced:

```sh
node scripts/keller-local.mjs cycle \
  --workspace "$PRIVATE_DRAFT_WORKSPACE" \
  --register "$NEW_REGISTER_BUNDLE/document-quotes.csv"

node estimator/node_modules/tsx/dist/cli.mjs estimator/src/order-cli.ts \
  "$ORDER_REQUEST" \
  --register "$NEW_REGISTER_BUNDLE/document-quotes.csv" \
  --out "$NEW_ORDER_PROPOSAL"
```

The request producer, reviewer, and scheduler must already be approved as described in [local automation](local-automation.md). The worker's existing job key and proof pin the chosen register bytes, so changing the register produces a separate draft rather than silently repricing an old receipt. JSON analogs and order Markdown identify the price basis, PDF path/hash, transcript hash, source field, and letter/date. Loading incomplete provenance or mixing incompatible sources within a curve fails before pricing. Legacy-register estimates remain numerically unchanged but warn that their prices are internal calculations.

Both paths still require human review. For complete priced proposals, the order schema requires explicit shipping and tax and blocks a grand total when a line or charge is missing. None of these artifacts authorizes customer delivery or fulfillment.

## Verification and evaluation

`node scripts/verify.mjs` runs the synthetic transcription and register-builder tests alongside the existing TypeScript, CLI, worker, and order-artifact checks. The Python fixtures contain no customer data. Real-corpus integrity, transcription coverage, price reconciliation, historical prediction accuracy, and host deployment are separate acceptance checks.

Keep `evals/evalset.jsonl` frozen: its target prices are internal calculations. Use it to verify that provenance-only changes leave the legacy numeric replay unchanged. A new document-grounded evaluation needs its own versioned case file and target-document digests, source-quote exclusion, exclusive quote-time cutoffs, held/unpriced counts, and a declared sampling method. Do not compare scores against different targets as if the estimator improved, or change targets to make existing tests pass. A matched-target comparison of different register sources is a data-source experiment, not a like-for-like code comparison accepted by `evals/compare.ts`.
