---
type: keller.catalog
---

# Keller source catalog

The source classes below are different evidence grains. A printed customer quote, an internal calculation, a supplier PO, an invoice, and a proposed order must not be mixed into one price basis. Follow the typed entries for their locations and limits.

- [[frozen-internal-register]]
- [[verified-customer-quote-corpus]]
- [[private-pdf-archive]]
- [[private-fabritrak-snapshot]]
- [[local-transcriptions]]
- [[source-audit]]

The approved private roots are bound outside the checkout through the ignored `.keller-local/arsumbris/sources.json` file. The environment variable names below describe locator roles, not a declaration that the host has exported them. `mcp.tool.keller_sources` exposes bounded read-only `list`, `read`, and DBF-query access to the bound `fabritrak`, `pdfs`, `transcripts`, and `manufacturing-audit` source sets; it does not pack those files into this graph or grant a write path. See [[arsumbris-workspace]] for access and validation.

[[map - Keller operator findings]] connects the dated source-coverage, evidence-quality, pricing and workflow findings to their typed grounds.
These retrospective operator records are not active quoting rules or blinded-worker context; their private originals remain outside Git.
