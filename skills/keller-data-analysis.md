---
type: mcp.skill::au-mcp-sdk
name: keller-data-analysis
description: Use for Keller quote-data analysis, SQL grains, price trends, customer/part summaries, and outcome-safe charts.
---

# Keller data analysis

Read `.agents/skills/keller-data-analysis/SKILL.md` in `keller-quotes` through the pinned read gate for the actual methodology, SQL, and source-grain constraints. This wrapper only makes that maintained guidance discoverable as a typed skill. `keller_polygres` and `keller_sources` support bounded cited lookups, not general aggregate SQL or full export; use the approved standalone workflow for those. Keep private rows and customer identities out of ordinary tracked notes and reports; historical posted status does not prove a win rate.
