---
type: source::au-base-types
tldr: "Official WonderSearch 0.2.0 documentation defines drive/folder scope, original uploads, receipts, pricing and revision-bound citations, not Keller authorization."
origin: https://docs.evokoa.com/wondersearch/sdk/installation
---

## Official evidence

- [Installation](https://docs.evokoa.com/wondersearch/sdk/installation): `wondersearch==0.2.0`, Python 3.10+, API origin `https://api.wondersearch.ai`; SDK recognizes `POLYGRES_API_KEY` and `POLYGRES_BASE_URL`. An omitted drive falls back to the workspace default, so this experiment must always bind an isolated drive.
- [Bulk imports](https://docs.evokoa.com/wondersearch/sdk/bulk-imports): `upload()` retains original files; direct text imports are different evidence. Freeze ordered original paths, bytes, hashes, folder and idempotency key before upload. Storage is reserved as files are accepted. SDK batching/transfer concurrency is not a cost or authorization control.
- [Recovery](https://docs.evokoa.com/wondersearch/sdk/upload-recovery): preserve accepted upload receipts, including partial failures; resume accepted processing by its receipt. The documented creation recovery window is 24 hours. A lost receipt is not authorization to blindly repeat.
- [Scope](https://docs.evokoa.com/wondersearch/search/scope): one drive per request; optional direct-folder scope is nonrecursive. Omitted/`None` folder searches the entire drive; `root` means direct root documents. This documentation does not establish an arbitrary document-ID/hash/date predicate or immutable case membership.
- [Search API and capabilities](https://docs.evokoa.com/wondersearch/reference/search-api): capabilities enumerate supported efforts; search results report requested and served effort. SDK 0.2.0 keeps these effort fields in `SearchResponse.raw`, not named dataclass attributes.
- [Efforts and limits](https://docs.evokoa.com/wondersearch/search/effort-and-limits): Small $0.001, Medium $0.0025, Large $0.01; up to ten results. The search-only forecast for 250 of each is $3.375. Returned `usage.cost` and served effort govern actual accounting. No retrieval score is a confidence percentage.
- [Billing](https://docs.evokoa.com/wondersearch/platform/billing): available and reserved credits differ; search and storage consume credits. This lane permits neither purchases nor storage upgrades. Unknown import/processing/storage charges are blockers, not assumed free.
- [Retries](https://docs.evokoa.com/wondersearch/sdk/errors-and-retries): the SDK has its own retry loop, including capacity retries. Setting an HTTP transport's retry count to zero alone is insufficient. SDK exceptions can contain sensitive request/response details and must not be printed.
- [Citations](https://docs.evokoa.com/wondersearch/search/results-and-citations): preserve returned passage text, drive/document/external identity, document revision and passage ID. UTF-8 byte offsets refer to extracted text, not source PDF pages. Search lacks a snapshot ID; never substitute the drive's latest snapshot to reconstruct one.

## Evidence limits

Documentation describes product contracts, not verified workspace credits, available storage, imported source identity, chronology, eligibility or permission to reveal original document text. A price-row allowance cannot silently become an original-document allowance. A physical folder needs a complete, immutable, independently verified membership binding before semantic search; checking returned hits afterward is insufficient.

The local synthetic SDK test is a request-shape test with in-memory transport, not a service capability, indexing, price-quality or billing test. No corpus records or per-case evidence belong in this public node.
