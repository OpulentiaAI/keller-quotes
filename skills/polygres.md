---
type: mcp.skill::au-mcp-sdk
name: polygres
description: Use when discovering or reading the Keller Polygres quote mirror and explicitly selected document corpus, with price-basis and read-only access boundaries.
---

# Keller Polygres evidence

Read `.agents/skills/polygres/SKILL.md` in `keller-quotes` through the pinned read gate before querying; it is the canonical connection, table, corpus, and export procedure. If unavailable, do not query from this summary. Select the approved corpus explicitly for bounded `keller_polygres` `search`/`page`/`prices` reads; `corpora` only discovers IDs. `keller_quote` separately exports the selected corpus read-only for an offline internal order draft. Never print a connection string, infer a price from search text, or treat a read credential as permission to import or alter data.
