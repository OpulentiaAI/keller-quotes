# Keller document index

Every retained PDF has a native `keller.document` record in `knowledge/documents/`. The index contains 39,975 documents and 39,975 distinct PDF hashes, including the zero-byte PDF and original transcription failures. These are metadata records, not an assertion that every document contains a usable price or proves a business event.

## Identity, associations and coverage

`document_id` is SHA-256 of the exact safe UTF-8 recovery alias in the pinned private archive catalog. The metadata records include the original PDF hash, associated transcription-record and transcript hashes when available, the original filename-only classification and extraction status, and a typed archive reference. Neither a filename classification nor extraction success verifies document issuer, first issuance, acceptance, payment or actual cost.

The builder joins each transcription record to its PDF through the exact `relative_source_path`, original PDF hash and byte count. Transcript associations require the original declared path, complete hash and byte count. It rejects mismatches and duplicate associations instead of guessing from a basename. One auxiliary metadata JSON is accounted for separately, not counted as another document.

The [frozen build manifest](../artifacts/keller-document-index-2026-10-07.json) records 39,975 associated transcription records, 39,796 associated successful transcripts, 178 failed records and one failed zero-byte PDF. These are the original transcription pipeline's states. Polygres's independently recovered Poppler page-text coverage is a different population and does not replace those states.

## Rebuild from verified private originals

First recover the authenticated source archive using [[git-evidence-access]]. Keep the recovered source and generated private index outside Git and every frozen blinded-worker allowance. The destination must be a new owner-private directory; the builder refuses existing output, unsafe paths, symlinks and byte changes.

```sh
umask 077
python3 -B scripts/index-keller-documents.py build \
  --catalog "$HOME/keller-private/evidence-2026-10-07-v1/keller-operator-evidence-catalog.private.json" \
  --catalog-sha256 3752d8823c5fb017fa86b61aec0d70e8a2b85472e857d2af114530bcd7fff2e7 \
  --restored-root "$HOME/keller-private/restored-evidence-2026-10-07-v1" \
  --out "$HOME/keller-private/document-index-2026-10-07-v1"
```

The outputs are `manifest.json`, public-safe `native-documents/`, and the operator-only `document-index.private.jsonl`. The manifest pins the builder and catalog and gives whole-index and aggregate native-file hashes. Compare those hashes with the tracked manifest before relying on the rebuilt derivative. Only the public-safe native metadata belongs in the graph.

## Private operator lookup

Select a native `document_id`, then query the complete, hash-pinned private JSONL index:

```sh
python3 -B scripts/index-keller-documents.py lookup \
  --index "$HOME/keller-private/document-index-2026-10-07-v1/document-index.private.jsonl" \
  --index-sha256 ccf7edd7d2adc11418718f005e5b92031621fcb3032d332a27a0e0256999e1a6 \
  --document-id "$DOCUMENT_ID"
```

Lookup validates the entire index, strict row structure, sorted unique IDs, alias-derived identity, and owner-only file access before returning the selected record. Its output contains private aliases and historical absolute locators. Use the recovery alias beneath the restored root; an old locator is provenance, not an approved current binding. Do not paste the result into typed knowledge, customer messages or a blinded worker's context.

The profile/tool allowlists are unchanged. This operator CLI does not mount original PDFs in the graph, add a worker tool, approve a quote or execute archived code.
