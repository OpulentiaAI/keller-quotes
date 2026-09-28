---
type: mcp.skill::au-mcp-sdk
name: keller-quote-register
description: Use when interpreting Keller quote-register schema, source fields, price-basis provenance, quote status, and historical analog limitations.
---

# Keller register reference

Read `.agents/skills/keller-quote-register/SKILL.md` in `keller-quotes` through the pinned read gate before querying or interpreting this register. The canonical file owns the full schema and caveats; do not rely on this wrapper if it cannot be read. Also inspect the typed [[source-catalog]] before crossing between internal calculations and printed customer prices. `keller_polygres` reads the selected PDF-price corpus; `keller_sources` lists or reads bound private originals and exact-quote DBF rows, never current validated costs.
