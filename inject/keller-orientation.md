---
type: mcp.inject::au-mcp-sdk
name: keller-orientation
description: Standing Keller quoting evidence and release boundaries for the read-only workspace profile.
---

Work from the typed [[source-catalog]] and [[organization-catalog]] and the canonical Keller skills in `.agents/skills/`. The source PDFs, DBFs, transcripts, and customer-specific outputs remain in approved private storage, not this repo. The Polygres corpus is a separately selected, immutable evidence basis; no quote outcome or current manufacturing cost is implied by a historical printed price.

Use graph reads, `keller_polygres` for selected corpus evidence, and `keller_sources` for bounded read-only private-source inspection. For an internal order draft, `keller_quote` requires an explicit corpus, JSON order request, and named reviewer; its structured order/Markdown/review response and persisted artifact references are private. Return a finite historical or operator-supported line price as a clearly marked provisional proposal even when technical evidence is incomplete; preserve the uncertainty and keep the human review gate. Hold only when no defensible numeric basis exists, and request one operator-supported unit price or cost-plus build rather than inventing a fallback. Internal quote and order artifacts require named human review before customer communication or release. This workspace does not activate a scheduler, update a database, call a model provider on its own, send a customer quote, or establish the requested ≥90% completed-quoting accuracy.
